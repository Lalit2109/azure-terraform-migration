"""
Git Manager for pushing exported Terraform code to Azure DevOps repositories
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote
from logger import get_logger


class GitManager:
    """Manages Git operations for pushing Terraform exports to repositories"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize Git Manager"""
        self.logger = get_logger()
        self.config = config
        self.azure_devops_config = config.get('azure_devops', {})
        self.git_config = config.get('git', {})
        
    def _get_repo_url(self, subscription: Dict[str, Any]) -> Optional[str]:
        """Get repository URL for a subscription using subscription name"""
        subscription_name = subscription.get('name')
        if not subscription_name:
            return None
        
        org = self.azure_devops_config.get('organization')
        project = self.azure_devops_config.get('project')
        
        if org and project:
            encoded_org = quote(org, safe='')
            encoded_project = quote(project, safe='')
            encoded_repo = quote(subscription_name, safe='')
            return f"https://dev.azure.com/{encoded_org}/{encoded_project}/_git/{encoded_repo}"
        
        return None
    
    def _get_pat_token(self) -> Optional[str]:
        """Get Azure DevOps PAT token from environment"""
        return os.getenv('AZURE_DEVOPS_PAT') or os.getenv('SYSTEM_ACCESS_TOKEN')
    
    def _get_branch(self, subscription: Dict[str, Any]) -> str:
        """Get main branch name"""
        base_branch = os.getenv('GIT_BRANCH') or self.git_config.get('branch', 'main')
        return base_branch
    
    def _get_backup_branch_name(self) -> str:
        """Get backup branch name with current date"""
        from datetime import datetime
        date_str = datetime.now().strftime('%Y-%m-%d')
        return f"backup-{date_str}"
    
    def _configure_git_credentials(self, repo_url: str) -> bool:
        """Configure git credentials for Azure DevOps"""
        pat_token = self._get_pat_token()
        if not pat_token:
            self.logger.error("Azure DevOps PAT token not found. Set AZURE_DEVOPS_PAT or SYSTEM_ACCESS_TOKEN")
            return False
        
        try:
            if 'dev.azure.com' in repo_url:
                org = self.azure_devops_config.get('organization')
                if org:
                    credential_url = f"https://{pat_token}@dev.azure.com/{org}"
                    git_config_cmd = [
                        'git', 'config', '--global',
                        f'url.{credential_url}/.insteadOf',
                        f'https://dev.azure.com/{org}/'
                    ]
                    subprocess.run(git_config_cmd, capture_output=True, text=True)
        except Exception as e:
            self.logger.warning(f"Could not configure git credentials: {str(e)}")
        
        return True
    
    def _init_git_repo(self, repo_path: Path) -> bool:
        """Initialize git repository if not already initialized"""
        git_dir = repo_path / '.git'
        if git_dir.exists():
            return True
        
        try:
            subprocess.run(
                ['git', 'init'],
                cwd=str(repo_path),
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False
    
    def _create_gitignore(self, repo_path: Path):
        """Create .gitignore file for Terraform"""
        gitignore_path = repo_path / '.gitignore'
        gitignore_content = """# Terraform files
*.tfstate
*.tfstate.*
*.tfvars
.terraform/
.terraform.lock.hcl
crash.log
crash.*.log
*.tfplan
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
"""
        gitignore_path.write_text(gitignore_content)
    
    def _create_readme(self, repo_path: Path, subscription: Dict[str, Any]):
        """Create README.md for the repository"""
        readme_path = repo_path / 'README.md'
        readme_content = f"""# Terraform Infrastructure as Code

This repository contains Terraform code for Azure resources exported from subscription: **{subscription.get('name', 'N/A')}**

## Subscription Information

- **Subscription ID**: `{subscription.get('id', 'N/A')}`
- **Subscription Name**: {subscription.get('name', 'N/A')}

## Structure

Each resource group is organized in its own directory:

```
resource-group-name/
├── main.tf
├── providers.tf
└── ...
```

## Usage

1. Navigate to a resource group directory:
   ```bash
   cd resource-group-name
   ```

2. Initialize Terraform:
   ```bash
   terraform init
   ```

3. Review the plan:
   ```bash
   terraform plan
   ```

## Notes

- This code was automatically generated using `aztfexport`
- Review and test before applying to production
- Update provider versions as needed
"""
        readme_path.write_text(readme_content)
    
    def _add_remote(self, repo_path: Path, repo_url: str) -> bool:
        """Add or update git remote"""
        try:
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=str(repo_path),
                capture_output=True
            )
            
            if result.returncode == 0:
                existing_url = result.stdout.decode().strip()
                if existing_url != repo_url:
                    subprocess.run(
                        ['git', 'remote', 'set-url', 'origin', repo_url],
                        cwd=str(repo_path),
                        check=True,
                        capture_output=True
                    )
            else:
                subprocess.run(
                    ['git', 'remote', 'add', 'origin', repo_url],
                    cwd=str(repo_path),
                    check=True,
                    capture_output=True
                )
            
            return True
        except subprocess.CalledProcessError:
            return False
    
    def _checkout_branch(self, repo_path: Path, branch: str) -> bool:
        """Create and checkout branch locally"""
        try:
            result = subprocess.run(
                ['git', 'checkout', '-b', branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return True
            elif 'already exists' in result.stderr.lower() or 'already on' in result.stderr.lower():
                result = subprocess.run(
                    ['git', 'checkout', branch],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            
            return False
        except Exception:
            return False
    
    def _create_backup_branch(self, repo_path: Path, branch: str, backup_branch: str, repo_url: str) -> bool:
        """Create a backup branch from the current branch"""
        try:
            result = subprocess.run(
                ['git', 'branch', backup_branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0 and 'already exists' not in result.stderr.lower():
                return False
            
            pat_token = self._get_pat_token()
            if not pat_token:
                return False
            
            if 'dev.azure.com' in repo_url:
                auth_url = f'https://{pat_token}@dev.azure.com'
                repo_url_with_auth = repo_url.replace('https://dev.azure.com', auth_url)
            else:
                repo_url_with_auth = repo_url
            
            push_result = subprocess.run(
                ['git', 'push', 'origin', backup_branch, '--force'],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
            )
            
            return push_result.returncode == 0
        except Exception:
            return False
    
    def _cleanup_old_backup_branches(self, repo_path: Path, repo_url: str, retention_count: int = 10) -> bool:
        """Clean up backup branches, keeping only the most recent N"""
        try:
            from datetime import datetime
            import re
            
            pat_token = self._get_pat_token()
            if not pat_token:
                return False
            
            if 'dev.azure.com' in repo_url:
                auth_url = f'https://{pat_token}@dev.azure.com'
                repo_url_with_auth = repo_url.replace('https://dev.azure.com', auth_url)
            else:
                repo_url_with_auth = repo_url
            
            result = subprocess.run(
                ['git', 'ls-remote', '--heads', repo_url_with_auth, 'backup-*'],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return True
            
            branches_with_dates = []
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                
                match = re.search(r'refs/heads/(backup-\d{4}-\d{2}-\d{2})', line)
                if match:
                    branch_name = match.group(1)
                    date_str = branch_name.replace('backup-', '')
                    try:
                        branch_date = datetime.strptime(date_str, '%Y-%m-%d')
                        branches_with_dates.append((branch_name, branch_date))
                    except ValueError:
                        continue

            if not branches_with_dates:
                return True

            branches_with_dates.sort(key=lambda x: x[1], reverse=True)

            branches_to_keep = [b for b, _ in branches_with_dates[:retention_count]]
            branches_to_delete = [b for b, _ in branches_with_dates[retention_count:]]

            if branches_to_delete:
                self.logger.info(
                    f"Cleaning up {len(branches_to_delete)} old backup branch(es) "
                    f"(keeping {len(branches_to_keep)} most recent)"
                )

                for branch in branches_to_delete:
                    try:
                        delete_result = subprocess.run(
                            ['git', 'push', 'origin', '--delete', branch],
                            cwd=str(repo_path),
                            capture_output=True,
                            text=True,
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
                        )
                        
                        if delete_result.returncode == 0:
                            self.logger.debug(f"Deleted old backup branch: {branch}")
                    except Exception:
                        pass
            
            return True
        except Exception:
            return False
    
    def _commit_changes(self, repo_path: Path, subscription: Dict[str, Any]) -> bool:
        """Commit all changes to git"""
        try:
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=str(repo_path),
                check=True,
                capture_output=True
            )
            
            commit_message = f"Export Terraform code for subscription: {subscription.get('name', subscription.get('id'))}"
            
            result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                cwd=str(repo_path),
                capture_output=True
            )
            
            if result.returncode == 0:
                self.logger.success(f"Committed changes: {commit_message}")
                return True
            elif 'nothing to commit' in result.stderr.decode().lower():
                self.logger.info("No changes to commit")
                return True
            else:
                return False
        except subprocess.CalledProcessError:
            return False
    
    def _push_to_remote(self, repo_path: Path, branch: str, repo_url: str) -> bool:
        """Push changes to remote repository"""
        pat_token = self._get_pat_token()
        if not pat_token:
            self.logger.error("PAT token not available for push")
            return False
        
        try:
            if 'dev.azure.com' in repo_url:
                auth_url = f'https://{pat_token}@dev.azure.com'
                repo_url_with_auth = repo_url.replace('https://dev.azure.com', auth_url)
            else:
                repo_url_with_auth = repo_url
            
            subprocess.run(
                ['git', 'remote', 'set-url', 'origin', repo_url_with_auth],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
                text=True
            )

            result = subprocess.run(
                ['git', 'push', '-u', 'origin', branch, '--force'],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
            )
            
            if result.returncode == 0:
                self.logger.success(f"Pushed to {branch} branch")
                return True
            else:
                error_msg = result.stderr or result.stdout
                self.logger.error(f"Failed to push: {error_msg}")
                
                if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                    self.logger.error("Repository does not exist in Azure DevOps.")
                    self.logger.error("Please create the repository first:")
                    self.logger.error(f"  Organization: {self.azure_devops_config.get('organization', 'N/A')}")
                    self.logger.error(f"  Project: {self.azure_devops_config.get('project', 'N/A')}")
                    self.logger.error(f"  Repository: {repo_url.split('/_git/')[-1] if '/_git/' in repo_url else 'N/A'}")
                
                return False
        except Exception as e:
            self.logger.error(f"Error during git push: {str(e)}")
            return False
    
    def push_to_repo(
        self,
        subscription: Dict[str, Any],
        export_path: Path
    ) -> bool:
        """Push exported Terraform code to Azure DevOps repository"""
        repo_url = self._get_repo_url(subscription)
        if not repo_url:
            self.logger.warning(f"No repository URL configured for subscription {subscription.get('id')}")
            return False
        
        main_branch = self._get_branch(subscription)
        backup_branch = self._get_backup_branch_name()
        retention_count = int(self.git_config.get('backup_retention_count', 10))
        
        self.logger.info(f"Pushing to repository: {repo_url}")
        self.logger.info(f"Main branch: {main_branch} (latest export)")
        self.logger.info(f"Backup branch: {backup_branch} (keeping last {retention_count} runs)")
        
        if not self._configure_git_credentials(repo_url):
            return False
        
        if not self._init_git_repo(export_path):
            return False
        
        self._create_gitignore(export_path)
        self._create_readme(export_path, subscription)
        
        if not self._add_remote(export_path, repo_url):
            return False
        
        if not self._checkout_branch(export_path, main_branch):
            self.logger.warning("Continuing with current branch")
        
        if not self._commit_changes(export_path, subscription):
            return False
        
        if not self._push_to_remote(export_path, main_branch, repo_url):
            return False
        
        self.logger.info(f"Creating backup branch: {backup_branch}")
        if not self._create_backup_branch(export_path, main_branch, backup_branch, repo_url):
            self.logger.warning("Failed to create backup branch, but main push succeeded")
        
        self.logger.info(f"Cleaning up backup branches, keeping last {retention_count} runs...")
        self._cleanup_old_backup_branches(export_path, repo_url, retention_count)
        
        self.logger.success(f"Successfully pushed to repository: {repo_url}")
        return True

