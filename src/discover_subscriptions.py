#!/usr/bin/env python3
"""
Discover Azure subscriptions and build matrix for Azure DevOps pipeline.
Supports targeted exports (single or multiple subscriptions) and SPN mapping.
"""

import os
import sys
import json
import argparse
import subprocess
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional


def get_subscriptions_from_azure() -> List[Dict[str, str]]:
    """Get all enabled subscriptions from Azure CLI"""
    try:
        result = subprocess.run(
            ['az', 'account', 'list', '--query', '[].{id:id, name:name, state:state}', '--output', 'json'],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )
        
        subs_data = json.loads(result.stdout)
        subscriptions = []
        
        for sub in subs_data:
            sub_id = sub.get('id', '').strip()
            sub_name = sub.get('name', '').strip()
            sub_state = sub.get('state', '').strip()
            
            if sub_id and sub_state.lower() == 'enabled':
                subscriptions.append({
                    'id': sub_id,
                    'name': sub_name or sub_id
                })
        
        return subscriptions
    except Exception as e:
        print(f"Error discovering subscriptions: {e}", file=sys.stderr)
        return []


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Could not load config: {e}", file=sys.stderr)
        return {}


def get_spn_mapping(subscription_id: str, subscription_name: str, config: Dict[str, Any]) -> str:
    """Get service connection for subscription with fallback to default"""
    spn_map = config.get('subscription_spn_map', {})
    default_spn = config.get('default_spn') or config.get('default_service_connection')
    
    # Check by subscription ID
    if subscription_id in spn_map:
        return spn_map[subscription_id]
    
    # Check by subscription name
    if subscription_name in spn_map:
        return spn_map[subscription_name]
    
    # Fallback to default
    if default_spn:
        return default_spn
    
    # Last resort: use variable from pipeline
    return os.getenv('defaultServiceConnection', '$(defaultServiceConnection)')


def should_exclude_subscription(subscription_id: str, subscription_name: str, config: Dict[str, Any]) -> bool:
    """Check if subscription should be excluded"""
    exclude_subs = config.get('exclude_subscriptions', {})
    
    if isinstance(exclude_subs, dict):
        prod_list = exclude_subs.get('prod', [])
        non_prod_list = exclude_subs.get('non-prod', [])
        exclude_list = (prod_list if isinstance(prod_list, list) else []) + \
                      (non_prod_list if isinstance(non_prod_list, list) else [])
    else:
        exclude_list = exclude_subs if isinstance(exclude_subs, list) else []
    
    return subscription_id in exclude_list or subscription_name in exclude_list


def build_matrix(
    subscriptions: List[Dict[str, str]],
    target_subscription_ids: Optional[str],
    all_subscriptions: bool,
    config: Dict[str, Any]
) -> Dict[str, Dict[str, str]]:
    """Build Azure DevOps matrix from subscriptions"""
    matrix = {}
    
    # Filter subscriptions
    if target_subscription_ids:
        target_ids = [s.strip() for s in target_subscription_ids.split(',') if s.strip()]
        subscriptions = [s for s in subscriptions if s['id'] in target_ids or s['name'] in target_ids]
    elif not all_subscriptions:
        return {}
    
    # Build matrix entries
    for sub in subscriptions:
        sub_id = sub['id']
        sub_name = sub['name']
        
        # Skip excluded subscriptions
        if should_exclude_subscription(sub_id, sub_name, config):
            continue
        
        # Create matrix key (sanitized subscription name)
        matrix_key = sub_name.lower().replace(' ', '_').replace('-', '_')
        matrix_key = ''.join(c for c in matrix_key if c.isalnum() or c == '_')
        
        # Get SPN mapping
        service_connection = get_spn_mapping(sub_id, sub_name, config)
        
        matrix[matrix_key] = {
            'subscriptionId': sub_id,
            'subscriptionName': sub_name,
            'serviceConnection': service_connection
        }
    
    return matrix


def main():
    parser = argparse.ArgumentParser(description='Discover subscriptions and build Azure DevOps matrix')
    parser.add_argument('--config', required=True, help='Path to subscriptions.yaml config file')
    parser.add_argument('--subscription-ids', default='', help='Comma-separated subscription IDs to target')
    parser.add_argument('--all-subscriptions', type=bool, default=True, help='Export all subscriptions')
    parser.add_argument('--output', required=True, help='Output JSON file for matrix')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Discover subscriptions
    print("Discovering subscriptions from Azure...")
    subscriptions = get_subscriptions_from_azure()
    
    if not subscriptions:
        print("No subscriptions found", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(subscriptions)} subscription(s)")
    
    # Build matrix
    matrix = build_matrix(
        subscriptions,
        args.subscription_ids if args.subscription_ids else None,
        args.all_subscriptions,
        config
    )
    
    if not matrix:
        print("No subscriptions to export after filtering", file=sys.stderr)
        sys.exit(1)
    
    print(f"Matrix will contain {len(matrix)} subscription(s)")
    
    # Output matrix as JSON (Azure DevOps format)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(matrix, f, indent=2)
    
    # Output in Azure DevOps variable format (escaped JSON)
    matrix_json = json.dumps(matrix).replace('"', '\\"')
    print(f"##vso[task.setvariable variable=subscriptionMatrix;isOutput=true]{matrix_json}")
    
    print(f"Matrix written to {output_path}")
    print(f"Matrix entries: {list(matrix.keys())}")
    
    # Also create a PowerShell script to set the matrix (for Azure DevOps)
    ps_script = output_path.parent / 'set_matrix.ps1'
    with open(ps_script, 'w') as f:
        f.write(f'$matrix = @\'\n')
        f.write(json.dumps(matrix, indent=2))
        f.write(f'\n\'@\n')
        f.write(f'Write-Host "Setting matrix with $($matrix | ConvertFrom-Json | Get-Member -MemberType NoteProperty | Measure-Object).Count entries"\n')
        f.write(f'$matrixJson = $matrix | ConvertFrom-Json | ConvertTo-Json -Compress\n')
        f.write(f'Write-Host "##vso[task.setvariable variable=subscriptionMatrix;isOutput=true]$matrixJson"\n')
    
    print(f"PowerShell script created: {ps_script}")


if __name__ == '__main__':
    main()

