# Azure Infrastructure Export to Terraform v2

Automated solution to export Azure infrastructure resources from multiple subscriptions using `aztfexport` with **matrix-based parallel execution**, organized into separate repositories for each subscription.

## Key Features

- ⚡ **Matrix-Based Parallel Execution**: Each subscription runs in its own parallel Azure DevOps job
- 🎯 **Subscription Selection**: Run for specific subscriptions or all subscriptions via pipeline parameters
- 🔐 **Per-Subscription SPN**: Each subscription can use its own service principal with fallback to default
- 📊 **Resource Group Level**: Export and track at resource group granularity
- 🚀 **Performance**: Reduce export time from ~10 hours to ~1-2 hours (with 10 parallel jobs)
- 🛡️ **Resilient Execution**: Failures in one subscription don't block others
- 🔄 **Git Integration**: Automatic commit and push to Azure DevOps repos with backup branches

## Architecture

The pipeline uses Azure DevOps **matrix strategy** where each subscription is processed in a separate parallel job:

```
Stage 1: Discover Subscriptions
  └── Discovers all enabled subscriptions
  └── Builds matrix with SPN mappings
  └── Outputs matrix for parallel execution

Stage 2: Export Subscriptions (Matrix)
  └── Each subscription = 1 parallel job
  └── Uses subscription-specific SPN (with fallback)
  └── Exports all resource groups
  └── Pushes to Git repository

Stage 3: Publish Results
  └── Aggregates export artifacts
```

## Prerequisites

- Python 3.10+
- Go 1.21+ (for aztfexport)
- Azure DevOps organization and project
- Azure service connection(s) with access to subscriptions
- Access to Azure subscriptions you want to export

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd aztfexportv2
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Subscriptions

Edit `pipelines/subscriptions.yaml`:

```yaml
# SPN Mapping (per-subscription service principals)
subscription_spn_map:
  "subscription-id-1": "spn-conn-sub1"
  "Production Subscription": "prod-azure-connection"

default_spn: "$(defaultServiceConnection)"

# Exclude subscriptions
exclude_subscriptions:
  prod: []
  non-prod: []

# Azure DevOps config
azure_devops:
  organization: "your-org"
  project: "your-project"
```

### 4. Set Up Azure DevOps Pipeline

1. **Create Variable Group**: `TerraformExport`
   - `defaultServiceConnection`: Your default Azure service connection name
   - `LOG_ANALYTICS_WORKSPACE_ID`: (Optional) Log Analytics workspace ID
   - `LOG_ANALYTICS_SHARED_KEY`: (Optional) Log Analytics shared key

2. **Import Pipeline**: Import `azure-pipelines.yml` to your Azure DevOps project

3. **Run Pipeline**: 
   - Scheduled: Runs weekly (Friday 8 AM UTC)
   - Manual: Click "Run pipeline" and set parameters

## Configuration

### SPN Mapping

Each subscription can have its own service principal with least-privilege access:

```yaml
subscription_spn_map:
  "subscription-id-1": "spn-conn-sub1"  # By ID
  "Production Subscription": "prod-conn"  # By name
  "subscription-id-2": "spn-conn-sub2"

default_spn: "$(defaultServiceConnection)"  # Fallback
```

**Fallback Logic:**
1. Check subscription ID in map
2. Check subscription name in map
3. Use default SPN
4. Continue execution (never fails due to missing SPN)

### Exclusion Rules

```yaml
# Exclude subscriptions
exclude_subscriptions:
  prod:
    - "subscription-id-prod-1"
  non-prod:
    - "Development Subscription"

# Exclude resource groups (wildcards supported)
global_excludes:
  resource_groups:
    - "NetworkWatcherRG_*"
    - "MC_*"
    - "AzureBackupRG_*"

# Exclude resource types
aztfexport:
  exclude_resource_types:
    - "Microsoft.Network/loadBalancers"
```

## Pipeline Parameters

When running manually, you can specify:

- **subscriptionIds**: Comma-separated subscription IDs (e.g., "sub-123,sub-456")
- **allSubscriptions**: `true` to export all, `false` for targeted export

## Performance

| Configuration | Runtime | Speedup |
|--------------|---------|---------|
| Sequential | ~10 hours | 1x |
| Matrix (5 parallel) | ~2 hours | 5x |
| Matrix (10 parallel) | ~1.5 hours | 10x |
| Matrix (20 parallel) | ~1 hour | 20x |

The `maxParallel: 10` setting in the pipeline limits concurrent jobs.

## Output Structure

```
exports/
├── production-subscription-1/
│   ├── resource-group-1/
│   │   ├── main.tf
│   │   ├── providers.tf
│   │   └── ...
│   ├── resource-group-2/
│   │   └── ...
│   └── .git/  (if git.push_to_repos: true)
├── development-subscription-1/
│   └── ...
└── export_results.json
```

## Git Repository Structure

Each subscription gets its own repository:

- **Main branch**: Latest export (force-pushed each run)
- **Backup branches**: `backup-YYYY-MM-DD` (retention configurable)

## Security

- ✅ **No global SPN**: Each subscription uses its own SPN (or fallback)
- ✅ **Least privilege**: SPNs should have Reader role only
- ✅ **Isolated execution**: Each subscription runs in separate job context
- ✅ **Service connections**: Locked per pipeline in Azure DevOps

## Troubleshooting

### Matrix Not Building

- Check Azure CLI authentication in discovery stage
- Verify `defaultServiceConnection` is set in variable group
- Review subscription discovery logs

### SPN Mapping Not Working

- Verify `subscription_spn_map` in config file
- Check service connection names match Azure DevOps
- Ensure fallback `default_spn` is configured

### Parallel Execution Issues

- Reduce `maxParallel` if agents are exhausted
- Check agent pool capacity
- Monitor resource usage (CPU, memory, disk)

## Documentation

- [Matrix Strategy Guide](docs/MATRIX_STRATEGY.md) - Detailed matrix implementation
- [PRD](docs/PRD.md) - Product requirements document
- [SaaS Plan](docs/SAAS_PLAN.md) - Future SaaS implementation plan

## License

[Add your license here]
