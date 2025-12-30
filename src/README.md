# Scripts

## discover_subscriptions.py

Discovers Azure subscriptions and builds a matrix for Azure DevOps pipeline matrix strategy.

### Usage

```bash
python src/discover_subscriptions.py \
  --config pipelines/subscriptions.yaml \
  --subscription-ids "sub-123,sub-456" \
  --all-subscriptions true \
  --output subscription_matrix.json
```

### Parameters

- `--config`: Path to subscriptions.yaml configuration file
- `--subscription-ids`: Comma-separated list of subscription IDs to target (optional)
- `--all-subscriptions`: Boolean flag to export all subscriptions (default: true)
- `--output`: Output JSON file path for the matrix

### Output

Creates a JSON file with matrix entries in the format:
```json
{
  "subscription_key": {
    "subscriptionId": "sub-123",
    "subscriptionName": "Production Subscription",
    "serviceConnection": "spn-conn-sub1"
  }
}
```

The script also sets an Azure DevOps pipeline variable `subscriptionMatrix` with the matrix data.

