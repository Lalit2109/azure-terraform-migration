"""
Main script to orchestrate Azure resource export to Terraform
Supports single subscription export (for matrix strategy) or all subscriptions
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

from export_manager import ExportManager
from git_manager import GitManager
from logger import get_logger


def main():
    """Main execution function"""
    logger = get_logger()
    
    config_path = os.getenv('CONFIG_PATH', 'pipelines/subscriptions.yaml')
    
    logger.info("=" * 70)
    logger.info("Azure Infrastructure Export to Terraform")
    logger.info("Using aztfexport for resource export")
    logger.info("=" * 70)
    logger.info("")
    
    export_manager = ExportManager(config_path)
    logger = get_logger()
    
    logger.info("Checking Azure CLI authentication...")
    az_cli_path = export_manager.az_cli_path
    
    try:
        result = subprocess.run(
            [az_cli_path, 'account', 'show'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            account_info = subprocess.run(
                [az_cli_path, 'account', 'show', '--query', '{name:name, id:id}', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if account_info.returncode == 0:
                account = json.loads(account_info.stdout)
                logger.success("Azure CLI is authenticated")
                logger.info(f"Account: {account.get('name', 'N/A')}")
                logger.info(f"Subscription ID: {account.get('id', 'N/A')}")
        else:
            logger.error("Not logged in to Azure CLI")
            logger.info("Please run: az login")
            sys.exit(1)
    except Exception as e:
        logger.warning(f"Error checking Azure CLI: {str(e)}")
        logger.info("Continuing anyway...")
    
    logger.info("")
    
    try:
        export_manager._install_aztfexport()
    except Exception as e:
        logger.error(f"Error with aztfexport: {str(e)}")
        sys.exit(1)
    
    Path(export_manager.base_dir).mkdir(parents=True, exist_ok=True)
    
    push_to_repos = os.getenv('PUSH_TO_REPOS', 'false').lower() == 'true'
    push_to_repos = push_to_repos or export_manager.config.get('git', {}).get('push_to_repos', False)
    
    # Check if single subscription export (matrix strategy)
    subscription_id = os.getenv('SUBSCRIPTION_ID')
    subscription_name = os.getenv('SUBSCRIPTION_NAME')
    
    if subscription_id:
        logger.info("=" * 70)
        logger.info("Single Subscription Export Mode (Matrix Strategy)")
        logger.info("=" * 70)
        logger.info(f"Subscription ID: {subscription_id}")
        logger.info(f"Subscription Name: {subscription_name or subscription_id}")
        logger.info("")
        
        subscription = {
            'id': subscription_id,
            'name': subscription_name or subscription_id
        }
        
        start_time = datetime.utcnow()
        subscription_result = None
        git_push_status = "skipped"
        error_message = None
        
        try:
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"Processing subscription: {subscription['name']}")
            logger.info("=" * 70)
            
            create_rg_folders = export_manager.config.get('output', {}).get('create_rg_folders', True)
            subscription_result = export_manager.export_subscription(subscription, create_rg_folders)
            end_time = datetime.utcnow()
            
            if subscription_result.get('successful_rgs', 0) > 0:
                status = "success"
            elif subscription_result.get('error'):
                status = "failed"
                error_message = subscription_result.get('error')
            else:
                status = "failed" if subscription_result.get('failed_rgs', 0) > 0 else "success"
            
            if push_to_repos and subscription_result.get('successful_rgs', 0) > 0:
                logger.info("")
                logger.info("=" * 70)
                logger.info(f"Pushing {subscription['name']} to Git Repository")
                logger.info("=" * 70)
                
                sub_dir = Path(export_manager.base_dir) / export_manager._sanitize_name(subscription['name'])
                
                if sub_dir.exists():
                    try:
                        success = export_manager.push_subscription_to_git(subscription, sub_dir)
                        if success:
                            logger.success(f"Successfully pushed {subscription['name']}")
                            git_push_status = "success"
                            
                            cleanup_after_push = export_manager.config.get('output', {}).get('cleanup_after_push', True)
                            if cleanup_after_push:
                                logger.info(f"Cleaning up export directory for {subscription['name']}...")
                                export_manager.cleanup_export_directory(subscription)
                        else:
                            logger.error(f"Failed to push {subscription['name']}")
                            git_push_status = "failed"
                    except Exception as e:
                        logger.error(f"Error pushing {subscription['name']}: {str(e)}")
                        git_push_status = "failed"
                        error_message = str(e) if not error_message else f"{error_message}; Git push error: {str(e)}"
                else:
                    logger.warning(f"Export directory not found for {subscription['name']}: {sub_dir}")
                    git_push_status = "failed"
            elif push_to_repos:
                logger.info(f"Skipping git push for {subscription['name']} (no successful exports)")
            
        except Exception as e:
            end_time = datetime.utcnow()
            error_message = str(e)
            logger.error(f"Fatal error exporting subscription {subscription_id}: {error_message}")
            import traceback
            traceback.print_exc()
            
            subscription_result = {
                'subscription_id': subscription_id,
                'subscription_name': subscription_name or subscription_id,
                'error': error_message
            }
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("Export Summary")
        logger.info("=" * 70)
        logger.info(f"Subscription: {subscription['name']}")
        if subscription_result:
            logger.info(f"Total resource groups: {subscription_result.get('total_rgs', 0)}")
            logger.info(f"Successfully exported: {subscription_result.get('successful_rgs', 0)}")
            logger.info(f"Failed: {subscription_result.get('failed_rgs', 0)}")
            logger.info(f"Git push: {git_push_status}")
        
        results_file = Path(export_manager.base_dir) / f'export_result_{subscription_id}.json'
        with open(results_file, 'w') as f:
            json.dump(subscription_result or {}, f, indent=2, default=str)
        logger.success(f"Export results saved to: {results_file}")
        
    else:
        logger.info("=" * 70)
        logger.info("All Subscriptions Export Mode")
        logger.info("=" * 70)
        logger.info("")
        
        logger.info("Discovering subscriptions from Azure...")
        subscriptions = export_manager.get_subscriptions_from_azure()
        
        if not subscriptions:
            logger.error("No subscriptions found. Check Azure CLI authentication and permissions.")
            sys.exit(1)
        
        exclude_subscriptions_raw = export_manager.config.get('exclude_subscriptions', {})
        if isinstance(exclude_subscriptions_raw, dict):
            prod_list = exclude_subscriptions_raw.get('prod') or []
            non_prod_list = exclude_subscriptions_raw.get('non-prod') or []
            exclude_subscriptions = (prod_list if isinstance(prod_list, list) else []) + \
                                  (non_prod_list if isinstance(non_prod_list, list) else [])
        else:
            exclude_subscriptions = exclude_subscriptions_raw if isinstance(exclude_subscriptions_raw, list) else []
        
        subscriptions_to_process = []
        excluded_subs = []
        
        for sub in subscriptions:
            subscription_id = sub.get('id')
            subscription_name = sub.get('name', subscription_id)
            
            matching_pattern = None
            if subscription_id in exclude_subscriptions:
                matching_pattern = subscription_id
            elif subscription_name in exclude_subscriptions:
                matching_pattern = subscription_name
            
            if matching_pattern:
                excluded_subs.append((subscription_name, subscription_id, matching_pattern))
            else:
                subscriptions_to_process.append(sub)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("Subscription Processing Summary")
        logger.info("=" * 70)
        
        if excluded_subs:
            logger.info(f"Excluded subscriptions ({len(excluded_subs)}):")
            for sub_name, sub_id, pattern in excluded_subs:
                logger.info(f"  ✗ {sub_name} (ID: {sub_id}) - matched exclude pattern: {pattern}")
        
        if subscriptions_to_process:
            logger.info(f"Subscriptions to process ({len(subscriptions_to_process)}):")
            for sub in subscriptions_to_process:
                sub_name = sub.get('name', sub.get('id'))
                sub_id = sub.get('id')
                logger.info(f"  ✓ {sub_name} (ID: {sub_id})")
        
        total_subs = len(subscriptions)
        logger.success(f"Found {total_subs} total subscription(s): {len(subscriptions_to_process)} to process, {len(excluded_subs)} excluded")
        logger.info("=" * 70)
        logger.info("")
        
        results = {}
        create_rg_folders = export_manager.config.get('output', {}).get('create_rg_folders', True)
        
        for sub in subscriptions_to_process:
            subscription_id = sub.get('id')
            subscription_name = sub.get('name', subscription_id)
            
            start_time = datetime.utcnow()
            subscription_result = None
            git_push_status = "skipped"
            error_message = None
            
            try:
                logger.info("")
                logger.info("=" * 70)
                logger.info(f"Processing subscription: {subscription_name}")
                logger.info("=" * 70)
                
                subscription_result = export_manager.export_subscription(sub, create_rg_folders)
                results[subscription_id] = subscription_result
                end_time = datetime.utcnow()
                
                if subscription_result.get('successful_rgs', 0) > 0:
                    status = "success"
                elif subscription_result.get('error'):
                    status = "failed"
                    error_message = subscription_result.get('error')
                else:
                    status = "failed" if subscription_result.get('failed_rgs', 0) > 0 else "success"
                
                if push_to_repos and subscription_result.get('successful_rgs', 0) > 0:
                    logger.info("")
                    logger.info("=" * 70)
                    logger.info(f"Pushing {subscription_name} to Git Repository")
                    logger.info("=" * 70)
                    
                    sub_dir = Path(export_manager.base_dir) / export_manager._sanitize_name(subscription_name)
                    
                    if sub_dir.exists():
                        try:
                            success = export_manager.push_subscription_to_git(sub, sub_dir)
                            if success:
                                logger.success(f"Successfully pushed {subscription_name}")
                                git_push_status = "success"
                                
                                cleanup_after_push = export_manager.config.get('output', {}).get('cleanup_after_push', True)
                                if cleanup_after_push:
                                    logger.info(f"Cleaning up export directory for {subscription_name}...")
                                    export_manager.cleanup_export_directory(sub)
                            else:
                                logger.error(f"Failed to push {subscription_name}")
                                git_push_status = "failed"
                        except Exception as e:
                            logger.error(f"Error pushing {subscription_name}: {str(e)}")
                            git_push_status = "failed"
                            error_message = str(e) if not error_message else f"{error_message}; Git push error: {str(e)}"
                    else:
                        logger.warning(f"Export directory not found for {subscription_name}: {sub_dir}")
                        git_push_status = "failed"
                elif push_to_repos:
                    logger.info(f"Skipping git push for {subscription_name} (no successful exports)")
                
            except Exception as e:
                end_time = datetime.utcnow()
                error_message = str(e)
                logger.error(f"Fatal error exporting subscription {subscription_id}: {error_message}")
                import traceback
                traceback.print_exc()
                
                results[subscription_id] = {
                    'subscription_id': subscription_id,
                    'subscription_name': subscription_name,
                    'error': error_message
                }
                
                logger.warning(f"Continuing with next subscription after error in {subscription_name}")
        
        if not results:
            logger.error("No subscriptions were exported. Check your configuration.")
            sys.exit(1)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("Export Summary")
        logger.info("=" * 70)
        
        total_subs = len(results)
        successful_subs = sum(1 for r in results.values() if r.get('successful_rgs', 0) > 0)
        total_rgs = sum(r.get('total_rgs', 0) for r in results.values())
        successful_rgs = sum(r.get('successful_rgs', 0) for r in results.values())
        
        logger.info(f"Subscriptions processed: {total_subs}")
        logger.info(f"Subscriptions with successful exports: {successful_subs}")
        logger.info(f"Total resource groups: {total_rgs}")
        logger.info(f"Successfully exported: {successful_rgs}")
        logger.info(f"Failed: {total_rgs - successful_rgs}")
        
        results_file = Path(export_manager.base_dir) / 'export_results.json'
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.success(f"Export results saved to: {results_file}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Export completed!")
    logger.info("=" * 70)
    logger.info(f"Output directory: {export_manager.base_dir}")
    logger.info("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger = get_logger()
        logger.info("")
        logger.info("Export cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger = get_logger()
        logger.error("")
        logger.error(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
