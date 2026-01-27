# OpenShift Workload Deployment Tool

A comprehensive Python script for deploying and managing workloads on OpenShift clusters with Disaster Recovery (DR) protection.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Command-Line Options](#command-line-options)
- [Usage Examples](#usage-examples)
- [Configuration File](#configuration-file)
- [Workload Types](#workload-types)
- [Multi-Namespace Deployment](#multi-namespace-deployment)
- [Cluster Selection Strategies](#cluster-selection-strategies)
- [DR Protection](#dr-protection)
- [Output Files](#output-files)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)
- [Advanced Usage](#advanced-usage)

---

## Overview

This tool automates the deployment of workloads to OpenShift clusters with built-in support for:
- Multiple workload types (ApplicationSet, Subscription, Distributed/Discovered)
- Disaster Recovery (DR) protection
- Multi-namespace deployment on the same cluster
- Flexible cluster selection strategies
- Support for various storage types (RBD, CephFS, Mixed)
- VM workload deployment
- Recipe-based and direct protection modes
- Consistency Group (CG) support

---

## Features

### Core Features
- ✅ Deploy to multiple OpenShift clusters
- ✅ Automated DR protection setup
- ✅ Support for distributed workloads (discovered apps)
- ✅ Multi-namespace deployment (multiple namespaces per workload group)
- ✅ Flexible cluster selection strategies
- ✅ Configuration file support
- ✅ Detailed deployment statistics and tracking
- ✅ Verbose logging for debugging

### Workload Support
- ✅ Busybox workloads
- ✅ MySQL workloads
- ✅ VM (Virtual Machine) workloads
- ✅ Custom workloads via Git repository

### Storage Types
- ✅ RBD (Ceph Block Device)
- ✅ CephFS (Ceph File System)
- ✅ Mixed workload storage

### DR Features
- ✅ DRPlacementControl (DRPC) creation
- ✅ Recipe-based protection
- ✅ Direct PVC/Pod protection
- ✅ Consistency Group (CG) support
- ✅ Multi-namespace protection in single DRPC

---

## Requirements

### System Requirements
- Python 3.6 or higher
- Git
- OpenShift CLI (`oc`) installed and configured
- Network access to target OpenShift clusters

### Python Dependencies
```bash
pip install pyyaml
```

### OpenShift Prerequisites
- Two OpenShift clusters configured for DR
- ACM (Advanced Cluster Management) deployed
- ODR (OpenShift DR) operator installed
- DRPolicy configured
- Valid kubeconfig files for both clusters

---

## Installation

1. **Clone or download the script:**
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. **Install Python dependencies:**
   ```bash
   pip install pyyaml
   ```

3. **Verify OpenShift CLI:**
   ```bash
   oc version
   ```

4. **Prepare workload data directory:**
   ```bash
   mkdir -p workload_data
   # Place required YAML templates in workload_data/
   # - placement.yaml
   # - drpc.yaml
   # - recipe.yaml (if using recipe protection)
   # - vrgc.yaml (if using CG)
   # - vm-secret.yaml (if deploying VMs)
   ```

---

## Quick Start

### Basic Deployment

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 2 \
  -output_dir my_deployment \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig /path/to/cluster1/kubeconfig \
  -c2_name cluster2 \
  -c2_kubeconfig /path/to/cluster2/kubeconfig \
  -drpolicy_name my-dr-policy
```

### Multi-Namespace Deployment

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 4 \
  -multi_ns_workload 2 \
  -output_dir multi_ns_test \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig /path/to/cluster1/kubeconfig \
  -c2_name cluster2 \
  -c2_kubeconfig /path/to/cluster2/kubeconfig \
  -drpolicy_name my-dr-policy
```

---

## Command-Line Options

### Required Options

| Option | Type | Description |
|--------|------|-------------|
| `-workload_pvc_type` | string | PVC storage type: `rbd`, `cephfs`, or `mix` |
| `-workload_type` | string | Workload deployment type: `appset`, `sub`, or `dist` |
| `-workload_count` | integer | Number of workload groups to deploy |
| `-output_dir` | string | Directory name for output files (created under `output_data/`) |
| `-protect_workload` | string | Enable DR protection: `yes` or `no` |
| `-c1_name` | string | Name of cluster 1 |
| `-c1_kubeconfig` | string | Path to cluster 1 kubeconfig file |
| `-c2_name` | string | Name of cluster 2 |
| `-c2_kubeconfig` | string | Path to cluster 2 kubeconfig file |

### Optional Options

#### Configuration & Logging

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-config` | path | None | Path to YAML configuration file |
| `-v, --verbose` | flag | False | Enable DEBUG level logging |

#### Workload Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-workload` | string | `busybox` | Workload application: `busybox`, `vm`, or `mysql` |
| `-multi_ns_workload` | integer | 1 | Number of namespaces per workload group (1-N) |
| `-ns_dr_prefix` | string | None | Prefix to add to all namespace names |

#### Cluster Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-clusterset` | string | Auto-detected | Cluster set name (auto-detected if not provided) |
| `-deploy_on` | string | None | Deploy all workloads to specific cluster |
| `-cluster_strategy` | string | `round_robin` | Cluster selection strategy: `round_robin`, `random`, or `least_loaded` |

#### DR Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-drpolicy_name` | string | None | Specific DR policy name (uses first available if not specified) |
| `-cg` | flag | False | Enable Consistency Group (CG) protection |
| `-recipe` | flag | False | Use recipe-based protection (only for `dist` type) |

#### Git Repository Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-repo` | string | Default OCS repo | Git repository URL for workload definitions |
| `-repo_branch` | string | `master` | Git branch to use |
| `-git_token` | string | None | GitHub token for private repositories |

---

## Usage Examples

### Example 1: Basic Distributed Workload Deployment

Deploy 5 busybox workloads with RBD storage and DR protection:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload busybox \
  -workload_count 5 \
  -output_dir example1 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- 5 namespaces created: `imp-busybox-rbd-1` through `imp-busybox-rbd-5`
- Distributed across cluster1 and cluster2 using round-robin
- Each namespace protected with individual DRPC

---

### Example 2: Multi-Namespace Deployment

Deploy 4 workload groups with 2 namespaces each:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 4 \
  -multi_ns_workload 2 \
  -output_dir example2 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m \
  -ns_dr_prefix prod
```

**Result:**
- 8 namespaces total (4 groups × 2 namespaces)
- Names: `prod-imp-busybox-rbd-multi-1-1`, `prod-imp-busybox-rbd-multi-1-2`, etc.
- 4 DRPCs (one per group, each protecting 2 namespaces)
- Round-robin distribution across clusters

---

### Example 3: Deploy All to One Cluster

Deploy all workloads to a specific cluster:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 10 \
  -multi_ns_workload 3 \
  -deploy_on cluster1 \
  -output_dir example3 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- 30 namespaces all on cluster1 (10 groups × 3 namespaces)
- 10 DRPCs, all with preferredCluster: cluster1
- Namespaces also created on cluster2 for DR failover capability

---

### Example 4: MySQL with Recipe Protection

Deploy MySQL workloads with recipe-based protection:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload mysql \
  -workload_count 3 \
  -multi_ns_workload 2 \
  -recipe \
  -output_dir example4 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- 6 MySQL namespaces (3 groups × 2 namespaces)
- 3 DRPCs with recipe-based protection
- 6 Recipe resources (one per namespace)
- Application-aware backup/restore configuration

---

### Example 5: VM Workloads with Custom Repository

Deploy VM workloads from custom Git repository:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload vm \
  -workload_count 2 \
  -multi_ns_workload 2 \
  -output_dir example5 \
  -protect_workload yes \
  -repo https://github.com/myorg/custom-workloads.git \
  -repo_branch main \
  -git_token ghp_xxxxxxxxxxxx \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- 4 VM workload namespaces (2 groups × 2 namespaces)
- VM secrets automatically created on both clusters
- Custom repository cloned and used for VM definitions
- DR protection configured for all VMs

---

### Example 6: Consistency Group (CG) Deployment

Deploy with Consistency Group protection:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload busybox \
  -workload_count 5 \
  -cg \
  -output_dir example6 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- 5 namespaces with CG-enabled naming
- VolumeGroupReplicationClass (VRGC) created on both clusters
- DRPCs with CG annotation enabled
- Crash-consistent group snapshots

---

### Example 7: Least-Loaded Strategy

Use least-loaded cluster selection strategy:

```bash
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 20 \
  -cluster_strategy least_loaded \
  -output_dir example7 \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/cluster1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/cluster2-config \
  -drpolicy_name dr-policy-5m
```

**Result:**
- Workloads distributed to cluster with fewer existing workloads
- Automatic load balancing
- Optimal resource utilization

---

### Example 8: Using Configuration File

Create a config file and use it:

**config.yaml:**
```yaml
# Cluster configuration
c1_name: "cluster1"
c1_kubeconfig: "~/.kube/cluster1-config"
c2_name: "cluster2"
c2_kubeconfig: "~/.kube/cluster2-config"

# Workload configuration
workload_type: "dist"
workload: "busybox"
workload_pvc_type: "rbd"
workload_count: 10
multi_ns_workload: 3

# DR configuration
protect_workload: "yes"
drpolicy_name: "dr-policy-5m"

# Output
output_dir: "large_deployment"
ns_dr_prefix: "prod"

# Strategy
cluster_strategy: "round_robin"
```

**Command:**
```bash
python3 deploy_workloads_multi_ns.py -config config.yaml -v
```

**Override from command line:**
```bash
python3 deploy_workloads_multi_ns.py -config config.yaml -workload_count 20 -v
```

---

## Configuration File

### Format

Configuration files use YAML format and can specify any command-line option.

### Example Configuration

```yaml
# config_example.yaml

# ============================================================================
# REQUIRED CONFIGURATION
# ============================================================================

# Cluster Configuration
c1_name: "c1-clustername"
c1_kubeconfig: "c1-clustername/auth/kubeconfig"
c2_name: "c2-clustername"
c2_kubeconfig: "c2-clustername/auth/kubeconfig"

# Workload Configuration
workload_pvc_type: "rbd"          # Options: rbd, cephfs, mix
workload_type: "dist"              # Options: appset, sub, dist
workload_count: 4                  # Number of workload groups

# Output Configuration
output_dir: "my_deployment"        # Directory for output files

# DR Configuration
protect_workload: "yes"            # Options: yes, no

# ============================================================================
# OPTIONAL CONFIGURATION
# ============================================================================

# Workload Options
workload: "busybox"                # Options: busybox, mysql, vm
multi_ns_workload: 2               # Number of namespaces per group (default: 1)
ns_dr_prefix: "prod"               # Prefix for namespace names

# Cluster Options
clusterset: "default"              # Cluster set name (auto-detected if omitted)
deploy_on: "baremetal5"            # Deploy to specific cluster (optional)
cluster_strategy: "round_robin"    # Options: round_robin, random, least_loaded

# DR Options
drpolicy_name: "odr-policy-5m"     # Specific DR policy (uses first if omitted)
cg: false                          # Enable Consistency Group (default: false)
recipe: false                      # Use recipe-based protection (default: false)

# Git Repository Options
repo: "https://github.com/red-hat-storage/ocs-workloads.git"
repo_branch: "master"
git_token: ""                      # GitHub token for private repos

# Logging
verbose: false                     # Enable debug logging (default: false)
```

### Usage

```bash
# Use configuration file
python3 deploy_workloads_multi_ns.py -config config_example.yaml

# Override specific options
python3 deploy_workloads_multi_ns.py -config config_example.yaml -workload_count 10

# Enable verbose logging
python3 deploy_workloads_multi_ns.py -config config_example.yaml -v
```

---

## Workload Types

### Distributed (dist) - Recommended

**Description:** Discovered applications deployed directly using kustomize.

**Features:**
- ✅ Direct deployment to clusters
- ✅ Full multi-namespace support
- ✅ Recipe-based protection support
- ✅ All cluster strategies supported
- ✅ Simplest and most flexible

**Usage:**
```bash
-workload_type dist
```

**Namespace Naming:**
- Single: `imp-{workload}-{pvc_type}-{counter}`
- Multi: `imp-{workload}-{pvc_type}-multi-{group}-{index}`

---

### ApplicationSet (appset)

**Description:** GitOps-based deployment using ArgoCD ApplicationSet.

**Features:**
- ✅ GitOps workflow
- ✅ ArgoCD integration
- ❌ No multi-namespace support
- ❌ No recipe protection

**Usage:**
```bash
-workload_type appset
```

**Requirements:**
- ArgoCD installed
- Git repository with workload definitions

---

### Subscription (sub)

**Description:** ACM Subscription-based deployment.

**Features:**
- ✅ ACM native deployment
- ✅ Channel-based delivery
- ❌ No multi-namespace support
- ❌ No recipe protection

**Usage:**
```bash
-workload_type sub
```

**Requirements:**
- ACM installed
- Git repository with workload definitions

---

## Multi-Namespace Deployment

### Overview

The `-multi_ns_workload` parameter allows deploying multiple isolated workloads in separate namespaces on the **same cluster**, all protected by a **single DRPC**.

### How It Works

```
-workload_count 2 -multi_ns_workload 3

Creates:
Group 1 (on cluster1):
  ├── namespace-multi-1-1  ← workload deployed
  ├── namespace-multi-1-2  ← workload deployed
  └── namespace-multi-1-3  ← workload deployed
  └── DRPC: protects all 3 namespaces

Group 2 (on cluster2):
  ├── namespace-multi-2-1  ← workload deployed
  ├── namespace-multi-2-2  ← workload deployed
  └── namespace-multi-2-3  ← workload deployed
  └── DRPC: protects all 3 namespaces
```

### Benefits

1. **Unified Protection**: All namespaces in a group protected by single DRPC
2. **Coordinated Failover**: All namespaces fail over together as a unit
3. **Simplified Management**: One DRPC to monitor per group
4. **Resource Efficiency**: Fewer DR resources to manage
5. **Logical Grouping**: Related workloads organized naturally

### Naming Convention

**Format:** `{prefix}-imp-{workload}-{pvc_type}-multi-{group_number}-{namespace_index}`

**Examples:**
```
# Without prefix
imp-busybox-rbd-multi-1-1
imp-busybox-rbd-multi-1-2

# With prefix
prod-imp-mysql-rbd-multi-3-1
prod-imp-mysql-rbd-multi-3-2
prod-imp-mysql-rbd-multi-3-3
```

### DRPC Structure

```yaml
apiVersion: ramendr.openshift.io/v1alpha1
kind: DRPlacementControl
metadata:
  name: prod-imp-busybox-rbd-1-multi
spec:
  drPolicyRef:
    name: dr-policy-5m
  preferredCluster: cluster1
  protectedNamespaces:
    - prod-imp-busybox-rbd-multi-1-1
    - prod-imp-busybox-rbd-multi-1-2
    - prod-imp-busybox-rbd-multi-1-3
  placementRef:
    name: prod-imp-busybox-rbd-1-multi-placs-1
```

### Use Cases

1. **Scale Testing**: Deploy many isolated workloads on single cluster
2. **Multi-Tenancy**: Separate namespaces for different teams/apps
3. **DR Testing**: Create multiple workload groups for failover testing
4. **Resource Optimization**: Efficient use of cluster resources

---

## Cluster Selection Strategies

### Round Robin (Default)

**Description:** Alternates between clusters sequentially.

**Usage:**
```bash
-cluster_strategy round_robin
```

**Behavior:**
```
Workload 1 → Cluster 1
Workload 2 → Cluster 2
Workload 3 → Cluster 1
Workload 4 → Cluster 2
```

**Best For:** Even distribution of workloads

---

### Random

**Description:** Randomly selects cluster for each workload.

**Usage:**
```bash
-cluster_strategy random
```

**Behavior:**
```
Workload 1 → Cluster 2 (random)
Workload 2 → Cluster 1 (random)
Workload 3 → Cluster 2 (random)
Workload 4 → Cluster 2 (random)
```

**Best For:** Testing unpredictable distribution

---

### Least Loaded

**Description:** Deploys to cluster with fewer existing workloads.

**Usage:**
```bash
-cluster_strategy least_loaded
```

**Behavior:**
```
Initial: Cluster1=0, Cluster2=0
Workload 1 → Cluster 1 (Now: Cluster1=1, Cluster2=0)
Workload 2 → Cluster 2 (Now: Cluster1=1, Cluster2=1)
Workload 3 → Cluster 1 (Now: Cluster1=2, Cluster2=1)
Workload 4 → Cluster 2 (Now: Cluster1=2, Cluster2=2)
```

**Best For:** Automatic load balancing

---

### Specified

**Description:** Deploy all workloads to specific cluster.

**Usage:**
```bash
-deploy_on cluster1
```

**Behavior:**
```
All workloads → Cluster 1
```

**Best For:** Single cluster testing or specific placement requirements

---

## DR Protection

### Protection Modes

#### 1. Direct Protection (Default)

Protects workloads using PVC and Pod selectors.

**Usage:**
```bash
-protect_workload yes
```

**DRPC Configuration:**
```yaml
spec:
  pvcSelector:
    matchExpressions:
      - key: workloadpattern
        operator: In
        values:
          - simple_io_pvc
  kubeObjectProtection:
    kubeObjectSelector:
      matchExpressions:
        - key: workloadpattern
          operator: In
          values:
            - simple_io
```

---

#### 2. Recipe-Based Protection

Application-aware protection with hooks and workflows.

**Usage:**
```bash
-protect_workload yes -recipe
```

**Requirements:**
- Only works with `-workload_type dist`
- Recipe template must exist in `workload_data/recipe.yaml`

**Features:**
- Pre/post backup hooks
- Application-specific workflows
- Consistent backup ordering

**Recipe Structure:**
```yaml
apiVersion: ramendr.openshift.io/v1alpha1
kind: Recipe
metadata:
  name: namespace-name
spec:
  appType: busybox
  groups:
    - name: namespace-name
      includedNamespaces:
        - namespace-name
      backupRef: namespace-name
  workflows:
    - name: backup
    - name: restore
  hooks:
    - name: pre-backup
      namespace: namespace-name
```

---

### Consistency Groups

Enable crash-consistent snapshots across multiple PVCs.

**Usage:**
```bash
-cg -protect_workload yes
```

**Requirements:**
- Only works with RBD storage (`-workload_pvc_type rbd`)
- Cannot use with CephFS

**Features:**
- VRGC (VolumeGroupReplicationClass) created automatically
- Crash-consistent group snapshots
- Coordinated replication

---

### DR Policies

**Auto-Detection:**
```bash
# Uses first available DRPolicy
-protect_workload yes
```

**Specific Policy:**
```bash
# Uses specified policy
-protect_workload yes -drpolicy_name dr-policy-5m
```

**List Available Policies:**
```bash
oc get drpolicy
```

---

## Output Files

### Directory Structure

```
output_data/
└── {output_dir}/
    ├── output_{prefix}_{type}_{pvc}_{workload}_combined.yaml
    └── (temporary files cleaned up automatically)
```

### File Naming

**Format:** `output_{prefix}_{workload_type}_{pvc_type}_{workload}_{multi}_combined.yaml`

**Examples:**
```
# Single namespace
output_dist_rbd_busybox_combined.yaml

# Multi-namespace
output_dist_rbd_busybox_multi2_combined.yaml

# With prefix
output_prod_dist_rbd_mysql_multi3_combined.yaml
```

### File Contents

The combined YAML file contains all DR resources:

```yaml
---
# Placement resources (one per workload group)
apiVersion: cluster.open-cluster-management.io/v1beta1
kind: Placement
...

---
# DRPC resources (one per workload group)
apiVersion: ramendr.openshift.io/v1alpha1
kind: DRPlacementControl
...

---
# Recipe resources (if using recipe protection)
apiVersion: ramendr.openshift.io/v1alpha1
kind: Recipe
...
```

---

## Verification

### Check Namespaces

```bash
# List all namespaces created
oc get namespaces | grep imp-

# Check specific namespace
oc get namespace imp-busybox-rbd-1

# Count namespaces on each cluster
oc --kubeconfig cluster1-config get ns | grep imp- | wc -l
oc --kubeconfig cluster2-config get ns | grep imp- | wc -l
```

### Check Workload Deployment

```bash
# Check pods in namespace
oc --kubeconfig cluster1-config get pods -n imp-busybox-rbd-1

# Check PVCs
oc --kubeconfig cluster1-config get pvc -n imp-busybox-rbd-1

# Check all resources
oc --kubeconfig cluster1-config get all -n imp-busybox-rbd-1
```

### Check DR Resources

```bash
# List all DRPCs
oc get drpc -A

# Check specific DRPC
oc get drpc imp-busybox-rbd-1-multi -o yaml

# Check protected namespaces
oc get drpc imp-busybox-rbd-1-multi -o jsonpath='{.spec.protectedNamespaces}' | jq

# Check preferred cluster
oc get drpc -o custom-columns=NAME:.metadata.name,PREFERRED:.spec.preferredCluster

# Check DRPC status
oc get drpc -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
```

### Check Placements

```bash
# List all placements
oc get placement -n openshift-dr-ops

# Check specific placement
oc get placement imp-busybox-rbd-1-multi-placs-1 -n openshift-dr-ops -o yaml
```

### Verify Multi-Namespace Protection

```bash
# For multi-namespace workloads, verify single DRPC protects all namespaces
oc get drpc base-imp-busybox-rbd-1-multi -o jsonpath='{.spec.protectedNamespaces}' | jq

# Expected output (example):
# [
#   "base-imp-busybox-rbd-multi-1-1",
#   "base-imp-busybox-rbd-multi-1-2"
# ]
```

### Check Recipes (if using recipe protection)

```bash
# List recipes
oc get recipe -A

# Check specific recipe
oc get recipe imp-busybox-rbd-1 -n imp-busybox-rbd-1 -o yaml
```

### Deployment Statistics

The script provides automatic statistics at the end:

```
======================================================================
DEPLOYMENT SUMMARY
======================================================================
Workload groups requested: 4
Namespaces per group:      2
Total namespaces created:  8
Successful deployments:    8 ✅
Failed deployments:        0 ❌

Distribution:
  cluster1: 4 namespaces
  cluster2: 4 namespaces
======================================================================
```

---

## Troubleshooting

### Common Issues

#### Issue 1: Missing Required Arguments

**Error:**
```
❌ Missing required arguments: workload_pvc_type, output_dir
```

**Solution:**
```bash
# Ensure all required options are provided
python3 deploy_workloads_multi_ns.py -config config.yaml
# OR
python3 deploy_workloads_multi_ns.py -workload_pvc_type rbd -output_dir test ...
```

---

#### Issue 2: Invalid Workload Type with Multi-Namespace

**Error:**
```
❌ -multi_ns_workload is only supported with -workload_type dist
```

**Solution:**
```bash
# Use dist workload type with multi-namespace
-workload_type dist -multi_ns_workload 2
```

---

#### Issue 3: CephFS with CG Not Supported

**Error:**
```
❌ CephFS with CG is not supported.
```

**Solution:**
```bash
# Use RBD with CG
-workload_pvc_type rbd -cg
```

---

#### Issue 4: Recipe with AppSet/Subscription

**Error:**
```
❌ Recipe does not work with appset.
```

**Solution:**
```bash
# Use dist workload type with recipe
-workload_type dist -recipe
```

---

#### Issue 5: Namespace Exists but No Pods

**Expected Behavior:** This is correct! Namespaces are created on BOTH clusters for DR, but workloads only deploy to ONE cluster.

**Verify:**
```bash
# Check which cluster has the workload
oc --kubeconfig cluster1-config get pods -n imp-busybox-rbd-1
oc --kubeconfig cluster2-config get pods -n imp-busybox-rbd-1

# Check DRPC to see preferred cluster
oc get drpc imp-busybox-rbd-1 -o jsonpath='{.spec.preferredCluster}'
```

---

#### Issue 6: Git Clone Failed

**Error:**
```
❌ Failed to clone repository: ...
```

**Solutions:**
```bash
# Check network connectivity
ping github.com

# For private repos, use git token
-git_token ghp_xxxxxxxxxxxx

# Verify branch exists
-repo_branch main  # or master

# Test manual clone
git clone --branch master https://github.com/repo/name.git
```

---

#### Issue 7: DRPolicy Not Found

**Error:**
```
❌ DRPolicy 'my-policy' not found
```

**Solutions:**
```bash
# List available policies
oc get drpolicy

# Use correct policy name
-drpolicy_name odr-policy-5m

# Or omit to use first available
# Script will auto-select first policy
```

---

#### Issue 8: Insufficient Permissions

**Error:**
```
❌ Failed to create project: Forbidden
```

**Solutions:**
```bash
# Verify kubeconfig is correct
oc --kubeconfig /path/to/config get nodes

# Check user permissions
oc whoami
oc auth can-i create project

# Ensure cluster-admin or sufficient permissions
```

---

### Debugging Tips

#### Enable Verbose Logging

```bash
python3 deploy_workloads_multi_ns.py -config config.yaml -v
```

#### Check Script Output Directory

```bash
ls -la output_data/
ls -la output_data/{your_output_dir}/
```

#### Verify Template Files Exist

```bash
ls -la workload_data/
# Should contain:
# - placement.yaml
# - drpc.yaml
# - recipe.yaml (if using recipe)
# - vrgc.yaml (if using CG)
# - vm-secret.yaml (if using VMs)
```

#### Test Cluster Connectivity

```bash
# Test cluster 1
oc --kubeconfig /path/to/cluster1/config get nodes

# Test cluster 2
oc --kubeconfig /path/to/cluster2/config get nodes
```

#### Dry-Run Kustomize

```bash
# Test kustomize manually
cd ocs-workloads/rdr/busybox/rbd/workloads/app-busybox-1
oc apply -k . --dry-run=client
```

---

## Best Practices

### 1. Start Small

```bash
# Test with minimal configuration first
-workload_count 1 -multi_ns_workload 1

# Then scale up
-workload_count 10 -multi_ns_workload 3
```

### 2. Use Configuration Files

```bash
# Create reusable configurations
python3 deploy_workloads_multi_ns.py -config prod_config.yaml

# Version control your configs
git add configs/prod_config.yaml
git commit -m "Add production deployment config"
```

### 3. Always Use Verbose Mode Initially

```bash
# Enable debug logging for first run
python3 deploy_workloads_multi_ns.py -config config.yaml -v
```

### 4. Verify Before Scaling

```bash
# Deploy 1-2 workloads first
-workload_count 2

# Verify deployment
oc get pods -A | grep imp-
oc get drpc -A

# Then scale up
-workload_count 50
```

### 5. Use Meaningful Prefixes

```bash
# Use descriptive prefixes for organization
-ns_dr_prefix prod     # Production workloads
-ns_dr_prefix test     # Test workloads
-ns_dr_prefix dev      # Development workloads
```

### 6. Monitor Resources

```bash
# Check cluster resources before large deployments
oc get nodes
oc describe node <node-name>

# Check storage capacity
oc get pv
```

### 7. Backup Configurations

```bash
# Save deployment outputs
cp output_data/my_deployment/*.yaml backups/

# Document deployment parameters
echo "Deployed $(date)" >> deployment_log.txt
```

### 8. Use Least-Loaded Strategy for Large Deployments

```bash
# For automatic load balancing
-workload_count 100 -cluster_strategy least_loaded
```

### 9. Test Failover

```bash
# After deployment, test DR failover
oc patch drpc <drpc-name> --type merge \
  -p '{"spec":{"action":"Failover","failoverCluster":"cluster2"}}'

# Verify workloads moved
oc --kubeconfig cluster2-config get pods -n <namespace>
```

### 10. Clean Up Test Deployments

```bash
# Delete test namespaces
oc delete namespace imp-busybox-rbd-test-1

# Delete DRPCs
oc delete drpc imp-busybox-rbd-test-1
```

---

## Advanced Usage

### Custom Workload Repository

```bash
# Use your own workload definitions
python3 deploy_workloads_multi_ns.py \
  -workload_type dist \
  -repo https://github.com/myorg/custom-workloads.git \
  -repo_branch develop \
  -git_token ghp_xxxxxxxxxxxx \
  ...
```

### Mixed Storage Types

```bash
# Deploy with mixed RBD and CephFS workloads
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type mix \
  ...
```

### Programmatic Integration

```python
# Integrate into automation scripts
import subprocess
import yaml

# Load configuration
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Run deployment
result = subprocess.run([
    'python3', 'deploy_workloads_multi_ns.py',
    '-config', 'config.yaml',
    '-workload_count', str(config['workload_count'])
], capture_output=True, text=True)

# Parse output
print(result.stdout)
if result.returncode != 0:
    print(f"Error: {result.stderr}")
```

### Batch Deployments

```bash
# Deploy multiple configurations sequentially
for config in configs/*.yaml; do
    echo "Deploying $config"
    python3 deploy_workloads_multi_ns.py -config "$config"
done
```

### Environment-Specific Deployments

```bash
# Development
python3 deploy_workloads_multi_ns.py \
  -config base_config.yaml \
  -ns_dr_prefix dev \
  -workload_count 5 \
  -output_dir dev_deployment

# Staging
python3 deploy_workloads_multi_ns.py \
  -config base_config.yaml \
  -ns_dr_prefix staging \
  -workload_count 10 \
  -output_dir staging_deployment

# Production
python3 deploy_workloads_multi_ns.py \
  -config base_config.yaml \
  -ns_dr_prefix prod \
  -workload_count 50 \
  -output_dir prod_deployment
```

---

## Support and Contribution

### Getting Help

1. Check the troubleshooting section
2. Review deployment logs with `-v` flag
3. Verify all prerequisites are met
4. Check OpenShift and ACM documentation

### Reporting Issues

When reporting issues, include:
- Complete command used
- Error messages (with `-v` enabled)
- OpenShift version
- ACM/ODR version
- Configuration file (if used)

### Feature Requests

Submit feature requests with:
- Use case description
- Expected behavior
- Current workaround (if any)

---

## License

[Add your license information here]

## Authors

[Add author information here]

## Acknowledgments

[Add acknowledgments here]

---

## Quick Reference

### Most Common Commands

```bash
# Basic deployment
python3 deploy_workloads_multi_ns.py \
  -workload_pvc_type rbd \
  -workload_type dist \
  -workload_count 5 \
  -output_dir test \
  -protect_workload yes \
  -c1_name cluster1 \
  -c1_kubeconfig ~/.kube/c1-config \
  -c2_name cluster2 \
  -c2_kubeconfig ~/.kube/c2-config \
  -drpolicy_name dr-policy-5m

# Multi-namespace deployment
python3 deploy_workloads_multi_ns.py \
  -config config.yaml \
  -multi_ns_workload 3

# All to one cluster
python3 deploy_workloads_multi_ns.py \
  -config config.yaml \
  -deploy_on cluster1

# With verbose logging
python3 deploy_workloads_multi_ns.py \
  -config config.yaml \
  -v
```

### Most Useful Verification Commands

```bash
# Check all namespaces
oc get ns | grep imp-

# Check all DRPCs
oc get drpc -A

# Check protected namespaces
oc get drpc <name> -o jsonpath='{.spec.protectedNamespaces}' | jq

# Check pods in namespace
oc get pods -n <namespace>

# Check deployment distribution
oc get drpc -o custom-columns=NAME:.metadata.name,CLUSTER:.spec.preferredCluster
```

---

**Last Updated:** 2025-01-27

**Script Version:** 2.0 (Multi-Namespace Support)