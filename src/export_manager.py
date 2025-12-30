"""
Azure Resource Export Manager
Uses aztfexport to export resources organized by subscription and resource group
"""

import os
import platform
import subprocess
import shutil
import fnmatch
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from logger import get_logger


class ExportManager:
    """Manages Azure resource exports using aztfexport"""
    
    def __init__(self, config_path: str = "pipelines/subscriptions.yaml"):
        """Initialize the export manager"""
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        log_level = self.config.get('logging', {}).get('level', os.getenv('LOG_LEVEL', 'INFO'))
        from logger import set_log_level
        set_log_level(log_level)
        self.logger = get_logger()
        
        self.base_dir = os.getenv('OUTPUT_DIR') or self.config.get('output', {}).get('base_dir', './exports')
        self.az_cli_path = self._find_az_cli()
    
    def _find_az_cli(self) -> str:
        """Find Azure CLI executable path (cross-platform)"""
        az_path = shutil.which('az')
        if az_path:
            return az_path
        
        system = platform.system()
        if system == 'Windows':
            common_paths = [
                os.path.expanduser('~\\AppData\\Local\\Programs\\Azure CLI\\az.exe'),
                'C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.exe',
            ]
        elif system == 'Darwin':
            common_paths = [
                '/opt/homebrew/bin/az',
                '/usr/local/bin/az',
                '/usr/bin/az',
            ]
        else:
            common_paths = [
                '/usr/bin/az',
                '/usr/local/bin/az',
                '/opt/az/bin/az',
            ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return 'az'
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _check_aztfexport_installed(self) -> bool:
        """Check if aztfexport is installed"""
        try:
            result = subprocess.run(
                ['aztfexport', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _install_aztfexport(self):
        """Install aztfexport if not present"""
        if self._check_aztfexport_installed():
            self.logger.success("aztfexport is already installed")
            return
        
        self.logger.info("Installing aztfexport...")
        try:
            subprocess.run(
                ['go', 'install', 'github.com/Azure/aztfexport@latest'],
                check=True
            )
            self.logger.success("aztfexport installed successfully")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.error("Could not install aztfexport automatically")
            self.logger.info("Please install manually:")
            self.logger.info("  Option 1: go install github.com/Azure/aztfexport@latest")
            self.logger.info("  Option 2: Download from https://github.com/Azure/aztfexport/releases")
            raise
    
    def _get_resource_groups(self, subscription_id: str, subscription_name: str = None) -> List[str]:
        """Get list of resource groups in a subscription using Azure CLI"""
        resource_groups = []
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        local_excludes = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        exclude_patterns = global_excludes + local_excludes
        
        sub_display = f" ({subscription_name})" if subscription_name else ""
        
        try:
            result = subprocess.run(
                [self.az_cli_path, 'group', 'list', '--subscription', subscription_id, '--output', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            rgs_data = json.loads(result.stdout)
            excluded_rgs = []
            
            for rg in rgs_data:
                rg_name = rg.get('name', '').strip()
                if rg_name:
                    matching_pattern = None
                    rg_name_lower = rg_name.lower()
                    for pattern in exclude_patterns:
                        pattern_lower = pattern.lower()
                        if rg_name_lower == pattern_lower:
                            matching_pattern = pattern
                            break
                        if fnmatch.fnmatchcase(rg_name_lower, pattern_lower):
                            matching_pattern = pattern
                            break
                    
                    if matching_pattern:
                        excluded_rgs.append((rg_name, matching_pattern))
                        continue
                    
                    if isinstance(rg_name, str) and rg_name:
                        resource_groups.append(rg_name)
            
            if excluded_rgs:
                self.logger.info(f"Excluded resource groups{sub_display}:")
                for rg_name, pattern in excluded_rgs:
                    self.logger.info(f"  ✗ {rg_name} (matched pattern: {pattern})")
            
            if resource_groups:
                self.logger.info(f"Resource groups to process{sub_display}:")
                for rg_name in resource_groups:
                    self.logger.info(f"  ✓ {rg_name}")
            
            total_rgs = len(resource_groups) + len(excluded_rgs)
            if excluded_rgs:
                self.logger.success(f"Found {total_rgs} total resource groups{sub_display}: {len(resource_groups)} to process, {len(excluded_rgs)} excluded")
            else:
                self.logger.success(f"Found {len(resource_groups)} resource groups{sub_display} (none excluded)")
            
            return resource_groups
            
        except Exception as e:
            self.logger.error(f"Error listing resource groups: {str(e)}")
            return []
    
    def _build_resource_graph_query(
        self,
        exclude_resource_types: List[str],
        custom_query: Optional[str] = None
    ) -> str:
        """Build Azure Resource Graph query to exclude resource types"""
        if custom_query:
            return custom_query
        
        if not exclude_resource_types:
            return ""
        
        conditions = []
        for resource_type in exclude_resource_types:
            escaped_type = resource_type.replace("'", "''")
            conditions.append(f"type != '{escaped_type}'")
        
        return " and ".join(conditions)
    
    def _export_resource_group(
        self,
        subscription_id: str,
        subscription_name: str,
        resource_group: str,
        output_path: Path
    ) -> bool:
        """Export a single resource group using aztfexport"""
        self.logger.info(f"Exporting resource group: {resource_group}")
        
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rg_name = str(resource_group).strip()
        
        exclude_resource_types = self.config.get('aztfexport', {}).get('exclude_resource_types', [])
        custom_query = self.config.get('aztfexport', {}).get('query', None)
        use_query_mode = bool(exclude_resource_types) or bool(custom_query)
        
        if use_query_mode:
            query = self._build_resource_graph_query(exclude_resource_types, custom_query)
            if query:
                self.logger.info("Using query mode to exclude resource types")
                if exclude_resource_types:
                    self.logger.debug(f"Excluding types: {', '.join(exclude_resource_types)}")
                
                cmd = [
                    'aztfexport',
                    'query',
                    '--subscription-id', subscription_id,
                    '--output-dir', str(output_path),
                    '--non-interactive',
                    '--plain-ui'
                ]
                
                if rg_name:
                    query_with_rg = f"{query} and resourceGroup == '{rg_name}'" if query else f"resourceGroup == '{rg_name}'"
                else:
                    query_with_rg = query
                
                additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
                cmd.extend(additional_flags)
                cmd.append(query_with_rg)
            else:
                use_query_mode = False
        
        if not use_query_mode:
            cmd = [
                'aztfexport',
                'resource-group',
                '--subscription-id', subscription_id,
                '--output-dir', str(output_path),
                '--non-interactive',
                '--plain-ui'
            ]
            
            resource_types = self.config.get('aztfexport', {}).get('resource_types', [])
            if resource_types:
                for rt in resource_types:
                    cmd.extend(['--resource-type', rt])
            
            exclude_resources = self.config.get('aztfexport', {}).get('exclude_resources', [])
            if exclude_resources:
                for er in exclude_resources:
                    cmd.extend(['--exclude', er])
            
            additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
            cmd.extend(additional_flags)
            cmd.append(rg_name)
        
        try:
            self.logger.debug(f"Running command: {' '.join(cmd)}")
            self.logger.info("This may take several minutes...")
            
            env = os.environ.copy()
            env['AZTFEXPORT_NON_INTERACTIVE'] = 'true'
            env['TERM'] = 'dumb'
            env['NO_COLOR'] = '1'
            
            script_cmd = shutil.which('script')
            
            if script_cmd:
                cmd_str = ' '.join(f'"{arg}"' if ' ' in arg or '"' in arg else arg for arg in cmd)
                script_wrapper = [script_cmd, '-q', '-e', '-c', cmd_str]
                final_cmd = script_wrapper
            else:
                final_cmd = cmd
            
            self.logger.info(f"Starting export for {resource_group}...")
            process = subprocess.Popen(
                final_cmd,
                cwd=str(Path(self.base_dir).resolve()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            output_lines = []
            seen_lines = set()
            
            try:
                import sys
                for line in iter(process.stdout.readline, ''):
                    if line:
                        line = line.rstrip()
                        if line not in seen_lines:
                            seen_lines.add(line)
                            output_lines.append(line)
                            sys.stdout.write(line + '\n')
                            sys.stdout.flush()
            finally:
                process.stdout.close()
                exit_code = process.wait(timeout=3600)
            
            full_output = '\n'.join(output_lines)
            self.logger.info("")
            if exit_code == 0:
                self.logger.success(f"✓ EXPORT COMPLETED SUCCESSFULLY for {resource_group}")
            else:
                self.logger.error(f"✗ EXPORT FAILED for {resource_group} (exit code: {exit_code})")
            
            if exit_code == 0:
                tf_files_direct = list(output_path.glob('*.tf'))
                tf_files_recursive = list(output_path.rglob('*.tf'))
                tf_files = tf_files_recursive if tf_files_recursive else tf_files_direct
                
                if tf_files:
                    self.logger.success(f"✓✓ Successfully exported {resource_group}")
                    self.logger.info(f"   Created {len(tf_files)} Terraform file(s)")
                    return True
                else:
                    self.logger.warning(f"⚠ Export completed but no .tf files found for {resource_group}")
                    return False
            else:
                self.logger.error(f"✗✗ Error exporting {resource_group} (exit code: {exit_code})")
                if full_output:
                    error_lines = full_output.strip().split('\n')
                    self.logger.error("   Error output (last 20 lines):")
                    for line in error_lines[-20:]:
                        if line.strip():
                            self.logger.error(f"     {line}")
                return False
                
        except subprocess.TimeoutExpired:
            if 'process' in locals():
                try:
                    process.kill()
                except:
                    pass
            self.logger.error(f"✗✗ Timeout exporting {resource_group} (exceeded 1 hour)")
            return False
        except FileNotFoundError:
            self.logger.error("aztfexport not found. Make sure it's installed and in PATH")
            return False
        except Exception as e:
            self.logger.error(f"Error exporting {resource_group}: {str(e)}")
            return False
    
    def export_subscription(
        self,
        subscription: Dict[str, Any],
        create_rg_folders: bool = True
    ) -> Dict[str, Any]:
        """Export all resource groups in a subscription"""
        subscription_id = subscription['id']
        subscription_name = subscription['name']
        
        self.logger.info("=" * 60)
        self.logger.info(f"Exporting subscription: {subscription_name}")
        self.logger.info(f"Subscription ID: {subscription_id}")
        self.logger.info("=" * 60)
        
        sub_dir = Path(self.base_dir) / self._sanitize_name(subscription_name)
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("Discovering resource groups...")
        resource_groups = self._get_resource_groups(subscription_id, subscription_name)
        
        results = {
            'subscription_id': subscription_id,
            'subscription_name': subscription_name,
            'resource_groups': {},
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0
        }
        
        if not resource_groups:
            self.logger.info("No resource groups to export")
            return results
        
        for rg in resource_groups:
            if create_rg_folders:
                rg_dir = sub_dir / self._sanitize_name(rg)
            else:
                rg_dir = sub_dir
            
            success = self._export_resource_group(
                subscription_id,
                subscription_name,
                rg,
                rg_dir
            )
            
            if success:
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'success'
                }
                results['successful_rgs'] += 1
            else:
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'failed'
                }
                results['failed_rgs'] += 1
        
        self.logger.success(f"Export completed for {subscription_name}")
        self.logger.info(f"Successful: {results['successful_rgs']}/{results['total_rgs']}")
        self.logger.info(f"Failed: {results['failed_rgs']}/{results['total_rgs']}")
        
        return results
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()
    
    def push_subscription_to_git(
        self,
        subscription: Dict[str, Any],
        export_path: Path
    ) -> bool:
        """Push exported subscription to git repository"""
        from git_manager import GitManager
        
        git_manager = GitManager(self.config)
        return git_manager.push_to_repo(subscription, export_path)
    
    def cleanup_export_directory(self, subscription: Dict[str, Any]) -> bool:
        """Clean up export directory after successful git push"""
        subscription_name = subscription.get('name')
        if not subscription_name:
            return False
        
        try:
            sub_dir = Path(self.base_dir) / self._sanitize_name(subscription_name)
            if sub_dir.exists():
                import shutil
                shutil.rmtree(sub_dir)
                self.logger.info(f"Cleaned up export directory: {sub_dir}")
                return True
        except Exception as e:
            self.logger.warning(f"Failed to cleanup export directory: {str(e)}")
            return False
