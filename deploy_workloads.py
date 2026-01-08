#!/usr/bin/env python3

"""
Deploys various types of workloads (ApplicationSet, Subscription, discovered)
to OpenShift clusters with options for Disaster Recovery protection.

Supports loading arguments from a config.yaml file.
"""

import argparse
import yaml
import random
from pathlib import Path
import subprocess
import sys
import os
import logging
import copy
import shutil
import json
from typing import List, Dict, Any, Optional

# --- Constants ---

# Set up logger. Level will be adjusted by args.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Base directory of the script
SCRIPT_DIR = Path(__file__).parent.resolve()

# Relative paths to data files
WORKLOAD_DATA_DIR = SCRIPT_DIR / "workload_data"
VM_SECRET_YAML = WORKLOAD_DATA_DIR / "vm-secret.yaml"
VM_SECRET_REG_YAML = WORKLOAD_DATA_DIR / "vm-secret-reg.yaml"
VM_REG_CERT_YAML = WORKLOAD_DATA_DIR / "vm-reg-cert.yaml"
PLACEMENT_YAML = WORKLOAD_DATA_DIR / "placement.yaml"
DRPC_YAML = WORKLOAD_DATA_DIR / "drpc.yaml"
RECIPE_YAML = WORKLOAD_DATA_DIR / "recipe.yaml"
VRGC_YAML = WORKLOAD_DATA_DIR / "vrgc.yaml"
DEFAULT_GIT_REPO = "https://github.com/red-hat-storage/ocs-workloads.git"
DEFAULT_GIT_BRANCH = "master"
CLONE_DIR_NAME = "ocs-workloads"
OUTPUT_DATA_DIR = "output_data"
OC_CMD = "oc"


# --- Argument Parsing ---

def parse_args():
    """Parse command-line arguments and (optionally) a config file."""
    parser = argparse.ArgumentParser(
        description='Deploy workloads to OCP clusters for DR testing.',
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # --- Config/Verbose Args ---
    # These are parsed first
    parser.add_argument(
        '-config', 
        type=Path, 
        help='Path to a config.yaml file. CLI args will override config file values.'
    )
    parser.add_argument(
        '-v', '--verbose', 
        action='store_true', 
        help='Enable DEBUG level logging'
    )

    # --- Deployment Args ---
    # Note: required=True is removed. We check manually in main() after loading config.
    parser.add_argument('-clusterset', type=str, default=None, help='Cluster set name')
    parser.add_argument('-c1_name', type=str, default=None, help='Cluster 1 name')
    parser.add_argument('-c1_kubeconfig', type=str, default=None, help='Cluster 1 Kubeconfig')
    parser.add_argument('-c2_name', type=str, default=None, help='Cluster 2 name')
    parser.add_argument('-c2_kubeconfig', type=str, default=None, help='Cluster 2 Kubeconfig')
    parser.add_argument('-workload_pvc_type', type=str, default=None, choices=['rbd', 'cephfs', 'mix'], help='Workload PVC type')
    parser.add_argument('-workload_type', type=str, default=None, choices=['appset', 'sub', 'dist'], help='Workload type')
    parser.add_argument('-workload_count', type=int, default=None, help='Number of workloads to deploy')
    parser.add_argument('-deploy_on', type=str, default=None, help='Deploy workload on specific cluster')
    parser.add_argument('-output_dir', type=str, default=None, help='Directory to write output YAML files (relative to script location)')
    parser.add_argument('-protect_workload', type=str, default=None, choices=['yes', 'no'], help='Protect the workload')
    parser.add_argument('-drpolicy_name', type=str, default=None, help='Disaster Recovery Policy name')
    parser.add_argument('-cg', action='store_true', help='Enable Consistency Group (CG)')
    parser.add_argument('-workload', type=str, default="busybox", choices=['busybox', 'vm', 'mysql'], help='Workload to deploy')
    parser.add_argument('-ns_dr_prefix', type=str, default=None, help='Name to add as prefix to namespaces')
    parser.add_argument('-recipe', action='store_true', help='Protect discovered workload using recipe')
    parser.add_argument('-repo', type=str, default=None, help='Repo to use for dist workloads')
    parser.add_argument('-repo_branch', type=str, default=DEFAULT_GIT_BRANCH, help='Branch to use for repo ')
    parser.add_argument('-git_token', type=str, default=None, help='Token to use for git clone')


    # --- Config File Loading Logic ---
    
    # 1. Parse just to get config_path and verbose flag
    known_args, _ = parser.parse_known_args()
    
    config_data = {}
    if known_args.config and known_args.config.exists():
        logger.info(f"Loading config from {known_args.config}")
        with open(known_args.config, 'r') as f:
            config_data = yaml.safe_load(f) or {} # Ensure it's a dict even if empty
    elif known_args.config:
        logger.warning(f"Config file not found: {known_args.config}")

    # 2. Set defaults from config_data.
    # This ensures config file values are used as defaults.
    # Any CLI args provided by the user will override these.
    parser.set_defaults(**config_data)
    
    # 3. Parse all args again, this time with the new defaults
    args = parser.parse_args()

    # --- Post-processing ---
    if args.workload_pvc_type == "mix":
        args.workload_pvc_type = "mix-workload"
    
    if args.output_dir:
        args.output_dir_path = SCRIPT_DIR / OUTPUT_DATA_DIR / args.output_dir
    else:
        args.output_dir_path = None # We'll check this in main
    
    return args


# --- Workload & Naming Logic ---

def get_workload_details(pvc_type: str, workload: str) -> Dict[str, str]:
    """Return workload path and selectors based on PVC type and workload."""
    logger.debug(f"Getting workload details for pvc_type={pvc_type}, workload={workload}")
    if workload == "busybox":
        if pvc_type == "mix-workload":
            path = "rdr/busybox/mix-workload/workloads/app-busybox-1"
            pod_key, pod_val = "workloadpattern", "simple_io"
            pvc_key, pvc_val = "appname", "busybox_app_mix"
        else:
            path = f"rdr/busybox/{pvc_type}/workloads/app-busybox-1"
            pod_key, pod_val = "workloadpattern", "simple_io"
            pvc_key, pvc_val = "workloadpattern", "simple_io_pvc"
    elif workload == "vm":
        path = "rdr/cnv-workload/vm-resources/vm-workload-1"
        pod_key, pod_val = "appname", "kubevirt"
        pvc_key, pvc_val = "appname", "kubevirt"
    else:  # mysql
        path = f"rdr/mysql/{pvc_type}/workloads/app-mysql-1"
        pod_key, pod_val = "appname", "mysql_app_1"
        pvc_key, pvc_val = "workloadpattern", "mysql_io_pvc"

    details = {
        "workload_path": path,
        "workload": workload,
        "workload_pod_selector_key": pod_key,
        "workload_pod_selector_value": pod_val,
        "workload_pvc_selector_key": pvc_key,
        "workload_pvc_selector_value": pvc_val
    }
    logger.debug(f"Workload details: {details}")
    return details

def generate_workload_name(workload_type: str, workload: str, pvc_type: str, counter: int, ns_dr_prefix: Optional[str], cg: bool, recipe: bool = False) -> str:
    """Generates a standardized workload/namespace name."""
    
    # Prefix
    if workload_type == "appset":
        type_prefix = "app"
    elif workload_type == "sub":
        type_prefix = "sub"
    else: # dist
        type_prefix = "imp"
        
    # Naming convention for CG
    workload_short = workload
    if cg:
        if workload == "busybox":
            workload_short = "bb"
        elif workload == "vm":
            workload_short = "vm" # Keep as is
        elif workload == "mysql":
            workload_short = "my"
        
        # Appset/Sub CGs have a different prefix
        if workload_type in ("appset", "sub"):
             type_prefix = "ap"

    ns_prefix = f"{ns_dr_prefix}-" if ns_dr_prefix else ""
    recipe_prefix = "rp-" if recipe else ""
    cg_suffix = "-cg" if cg else ""

    name = f"{ns_prefix}{type_prefix}-{workload_short}-{pvc_type}-{recipe_prefix}{counter}{cg_suffix}"
    logger.debug(f"Generated workload name: {name}")
    return name


# --- YAML & Git Utilities ---

def load_yaml_file(filepath: Path) -> List[Dict[str, Any]]:
    """Load and return YAML content from the given file."""
    logger.debug(f"Loading YAML file: {filepath}")
    try:
        with open(filepath, 'r') as file:
            return list(yaml.safe_load_all(file))
    except FileNotFoundError:
        logger.error(f"❌ YAML file not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to load YAML file {filepath}: {e}")
        sys.exit(1)

def write_output_yaml(data: List[Dict[str, Any]], output_path: Path) -> None:
    """Write YAML data (list of docs) to a file."""
    logger.debug(f"Writing {len(data)} YAML documents to {output_path}")
    try:
        with open(output_path, 'w') as outfile:
            if data:
                yaml.dump_all(data, outfile, sort_keys=False, indent=2)
            else:
                logger.warning(f"⚠ No data to write to {output_path}")
    except Exception as e:
        logger.error(f"❌ Failed to write YAML to {output_path}: {e}")

def clone_and_checkout(repo_url: str, clone_path: Path, branch: str) -> None:
    """Clone the Git repository and checkout the specified branch."""
    if clone_path.exists():
        logger.info(f"Directory {clone_path} already exists. Removing it.")
        try:
            shutil.rmtree(clone_path)
        except OSError as e:
            logger.error(f"❌ Failed to remove existing clone directory {clone_path}: {e}")
            sys.exit(1)
    
    try:
        logger.info(f"Cloning repository {repo_url} (branch: {branch}) into {clone_path}")
        result = subprocess.run(
            ["git", "clone", "--quiet", "--branch", branch, repo_url, str(clone_path)],
            check=True, capture_output=True, text=True
        )
        logger.debug(f"Git clone stdout: {result.stdout}")
        logger.debug(f"Git clone stderr: {result.stderr}")
        logger.info("✅ Repository cloned successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to clone repository: {e.stderr}")
        sys.exit(1)


# --- OpenShift/`oc` Command Wrappers ---

def run_oc_command(cmd_args: List[str], kubeconfig: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Helper to run an 'oc' command."""
    base_cmd = [OC_CMD]
    if kubeconfig:
        base_cmd.extend(["--kubeconfig", str(kubeconfig)])
    base_cmd.extend(cmd_args)
    
    logger.debug(f"Running command: {' '.join(base_cmd)}")
    result = subprocess.run(base_cmd, capture_output=True, text=True, check=check)
    
    if result.stderr and check: # Don't log stderr if check=False and it's expected
        logger.debug(f"Command stderr: {result.stderr.strip()}")
    if result.stdout:
        logger.debug(f"Command stdout: {result.stdout.strip()}")
        
    return result

def create_project(kubeconfig: str, cluster_name: str, project_name: str) -> None:
    """Create a project if it does not already exist."""
    try:
        run_oc_command(["new-project", project_name], kubeconfig)
        logger.info(f"✅ Project '{project_name}' created on {cluster_name}.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "already exists" in stderr:
            logger.info(f"⚠ Project '{project_name}' already exists on {cluster_name}, skipping creation.")
        else:
            logger.error(f"❌ Failed to create project '{project_name}' on {cluster_name}:\n{stderr}")
            raise

def create_resource(kubeconfig: str, cluster_name: str, yaml_file: Path, resource_label: str) -> None:
    """Create a resource from a YAML file if it does not already exist."""
    try:
        run_oc_command(["create", "-f", str(yaml_file)], kubeconfig)
        logger.info(f"✅ Created {resource_label} on {cluster_name}.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "AlreadyExists" in stderr or "already exists" in stderr:
            logger.info(f"⚠ {resource_label} already exists on {cluster_name}, skipping creation.")
        else:
            logger.error(f"❌ Failed to create {resource_label} on {cluster_name}:\n{stderr}")
            raise

def get_managed_clusters() -> List[str]:
    """Get list of managed clusters using JSON output for robustness."""
    logger.debug("Getting managed clusters...")
    try:
        result = run_oc_command(["get", "managedcluster", "-o", "json"])
        data = json.loads(result.stdout)
        clusters = []
        for item in data.get("items", []):
            name = item.get("metadata", {}).get("name")
            status = item.get("status", {}).get("conditions", [{}])[-1].get("type")
            if name != "local-cluster" and status not in ("Unknown", "ManagedClusterConditionUnknown"):
                clusters.append(name)
        logger.debug(f"Found managed clusters: {clusters}")
        return clusters
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to get managed clusters: {e.stderr}")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"❌ Failed to parse JSON output from 'oc get managedcluster'")
        sys.exit(1)

def get_clusterset_name(cluster_name: str) -> Optional[str]:
    """Get clusterset name for a given cluster."""
    logger.debug(f"Getting clusterset for {cluster_name}")
    try:
        result = run_oc_command(["get", "managedcluster", cluster_name, "-o", "yaml"])
        data = yaml.safe_load(result.stdout)
        clusterset = data.get("metadata", {}).get("labels", {}).get("cluster.open-cluster-management.io/clusterset")
        logger.debug(f"Found clusterset: {clusterset}")
        return clusterset
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to get clusterset for {cluster_name}: {e.stderr}")
        sys.exit(1)

def validate_drpolicy(drpolicy_name: str) -> None:
    """Validate given drpolicy exists."""
    logger.debug(f"Validating DRPolicy: {drpolicy_name}")
    try:
        run_oc_command(["get", "drpolicy", drpolicy_name])
        logger.info(f"✅ DRPolicy '{drpolicy_name}' validated.")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ DRPolicy '{drpolicy_name}' not found or inaccessible: {e.stderr}")
        sys.exit(1)

def get_existing_workload_count(workload_type: str, pvc_type: str, workload: str, cg: bool, kubeconfig: str) -> int:
    """Get count of existing workloads to create dynamic names."""
    logger.debug("Getting existing workload count...")
    try:
        if workload_type == "appset":
            resource = "ApplicationSet.argoproj.io"
            cmd_args = ["get", resource, "-A", "-o", "name"]
        elif workload_type == "sub":
            resource = "Subscription.apps.open-cluster-management.io"
            cmd_args = ["get", resource, "-A", "-o", "name"]
        else: # dist
            resource = "namespace"
            cmd_args = ["get", resource, "--no-headers", "-o", "name", "--kubeconfig", kubeconfig]
        
        result = run_oc_command(cmd_args)
        
        # Adjust search terms for CG
        search_workload = workload
        if cg and workload_type in ("appset", "sub"):
            if workload == "busybox":
                search_workload = "bb"
            elif workload == "mysql":
                search_workload = "my"
        
        search_prefix = "imp-" if workload_type == "dist" else ""

        count = sum(
            1 for line in result.stdout.splitlines()
            if search_prefix in line and pvc_type in line and search_workload in line
        )
        logger.info(f"Found {count} existing '{workload_type}' workloads matching criteria.")
        return count
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to count existing {resource}: {e.stderr}")
        return 0 # Default to 0 if count fails

# --- VM & VRGC Specific Logic ---

def handle_vm_resources(c1_dict: Dict, c2_dict: Dict, namespace: str, vm_secret_template_path: Path, vm_secret_reg_template_path: Path, vm_reg_cert_template_path: Path) -> None:
    """Creates project and VM secret on both clusters for a given namespace."""
    logger.info(f"Setting up VM resources for namespace '{namespace}'...")
    try:
        # 1. Create projects
        create_project(c1_dict["kubeconfig"], c1_dict["cluster_name"], namespace)
        create_project(c2_dict["kubeconfig"], c2_dict["cluster_name"], namespace)

        # 2. Load, update, and write temp secret file
        vm_secret_yaml_dict = load_yaml_file(vm_secret_template_path)[0]
        vm_secret_yaml_dict["metadata"]["namespace"] = namespace
        
        temp_secret_path = SCRIPT_DIR / OUTPUT_DATA_DIR  / f"temp-vm-secret-{namespace}.yaml"
        write_output_yaml([vm_secret_yaml_dict], temp_secret_path)
        logger.debug(f"Wrote temporary VM secret to {temp_secret_path}")
        if vm_secret_reg_template_path:
            vm_secret_reg_yaml_dict = load_yaml_file(vm_secret_reg_template_path)[0]
            vm_secret_reg_yaml_dict["metadata"]["namespace"] = namespace
            
            temp_secret_reg_path = SCRIPT_DIR / OUTPUT_DATA_DIR / f"temp-vm-secret-reg-{namespace}.yaml"
            write_output_yaml([vm_secret_reg_yaml_dict], temp_secret_reg_path)
            logger.debug(f"Wrote temporary VM secret Reg to {temp_secret_reg_path}")
        

        if vm_reg_cert_template_path:
            vm_reg_cert_yaml_dict = load_yaml_file(vm_reg_cert_template_path)[0]
            vm_reg_cert_yaml_dict["metadata"]["namespace"] = namespace
            
            temp_reg_cert_path = SCRIPT_DIR / OUTPUT_DATA_DIR  / f"temp-vm-reg-cert-{namespace}.yaml"
            write_output_yaml([vm_reg_cert_yaml_dict], temp_reg_cert_path)
            logger.debug(f"Wrote temporary VM secret Reg to {temp_reg_cert_path}")

        # 3. Create secret on both clusters
        create_resource(c1_dict["kubeconfig"], c1_dict["cluster_name"], temp_secret_path, f"vm-secret in {namespace}")
        create_resource(c2_dict["kubeconfig"], c2_dict["cluster_name"], temp_secret_path, f"vm-secret in {namespace}")
        if vm_secret_reg_template_path:
            create_resource(c1_dict["kubeconfig"], c1_dict["cluster_name"], temp_secret_reg_path, f"vm-secret-reg in {namespace}")
            create_resource(c2_dict["kubeconfig"], c2_dict["cluster_name"], temp_secret_reg_path, f"vm-secret-reg in {namespace}")
        if vm_reg_cert_template_path:
            create_resource(c1_dict["kubeconfig"], c1_dict["cluster_name"], temp_reg_cert_path, f"vm-reg-cert in {namespace}")
            create_resource(c2_dict["kubeconfig"], c2_dict["cluster_name"], temp_reg_cert_path, f"vm-reg-cert in {namespace}")

        # 4. Clean up temp file
        temp_secret_path.unlink()
        logger.debug(f"Cleaned up {temp_secret_path}")

    except Exception as e:
        logger.error(f"❌ Failed during VM resource setup for {namespace}: {e}")
        # Don't exit, but log the error
        
def get_first_vrc_yaml(kubeconfig: str) -> Dict[str, Any]:
    """Get the YAML of the first VolumeReplicationClass from a cluster."""
    logger.debug(f"Getting first VRC from {kubeconfig}")
    try:
        result = run_oc_command(["get", "vrc", "-o", "name"], kubeconfig)
        vrc_list = result.stdout.splitlines()
        if not vrc_list:
            raise RuntimeError(f"No VRCs found in cluster with kubeconfig {kubeconfig}")

        vrc_name = vrc_list[0]
        logger.debug(f"Found VRC: {vrc_name}")
        result = run_oc_command(["get", vrc_name, "-o", "yaml"], kubeconfig)
        return yaml.safe_load(result.stdout)
    except (subprocess.CalledProcessError, RuntimeError) as e:
        logger.error(f"❌ {e}")
        sys.exit(1)

def update_vrgc_from_vrc(vrgc_dict: Dict, vrc_dict: Dict) -> None:
    """Update VRGC YAML dict based on VRC data."""
    logger.debug("Updating VRGC template from VRC data")
    vrc_params = vrc_dict.get('spec', {}).get('parameters', {})
    vrc_labels = vrc_dict.get('metadata', {}).get('labels', {})

    vrgc_dict['metadata']['name'] = f"vrgc-rbd-{vrc_params.get('schedulingInterval')}"
    labels = vrgc_dict.setdefault('metadata', {}).setdefault('labels', {})
    labels['ramendr.openshift.io/storageid'] = vrc_labels.get('ramendr.openshift.io/storageid')
    labels['ramendr.openshift.io/replicationid'] = vrc_labels.get('ramendr.openshift.io/replicationid')

    params = vrgc_dict.setdefault('spec', {}).setdefault('parameters', {})
    params['clusterID'] = vrc_params.get('clusterID')
    params['replication.storage.openshift.io/group-replication-secret-name'] = vrc_params.get('replication.storage.openshift.io/replication-secret-name')
    params['schedulingInterval'] = vrc_params.get('schedulingInterval')

def ensure_vrgc_exists(kubeconfig: str, cluster_name: str, vrgc_dict: Dict, output_path: Path) -> None:
    """Check if VRGC exists, create if missing."""
    vrgc_name = vrgc_dict['metadata']['name']
    logger.debug(f"Ensuring VRGC '{vrgc_name}' exists in {cluster_name}")
    try:
        run_oc_command(["get", "VolumeGroupReplicationClass", vrgc_name], kubeconfig)
        logger.info(f"✅ VRGC '{vrgc_name}' already exists in {cluster_name}, skipping creation.")
    except subprocess.CalledProcessError:
        logger.info(f"⚠ VRGC '{vrgc_name}' not found in {cluster_name}. Creating...")
        try:
            write_output_yaml(vrgc_dict, output_path)
            create_resource(kubeconfig, cluster_name, output_path, f"VRGC '{vrgc_name}'")
            output_path.unlink() # Clean up temp file
        except Exception as e:
            logger.error(f"❌ Failed to create VRGC '{vrgc_name}' in {cluster_name}: {e}")
            sys.exit(1)

def create_vrgc_on_clusters(args: argparse.Namespace) -> None:
    """Creating VolumeGroupReplicationClass in both clusters."""
    logger.info("Setting up VolumeGroupReplicationClass (VRGC) for CG...")
    vrgc_template = load_yaml_file(VRGC_YAML)[0]
    temp_vrgc_path = WORKLOAD_DATA_DIR / "temp-vrgc.yaml"

    # Cluster 1
    vrc_c1_dict = get_first_vrc_yaml(args.c1_kubeconfig)
    vrgc_c1_dict = vrgc_template.copy()
    update_vrgc_from_vrc(vrgc_c1_dict, vrc_c1_dict)
    ensure_vrgc_exists(args.c1_kubeconfig, args.c1_name, vrgc_c1_dict, temp_vrgc_path)

    # Cluster 2
    vrc_c2_dict = get_first_vrc_yaml(args.c2_kubeconfig)
    vrgc_c2_dict = vrgc_template.copy()
    update_vrgc_from_vrc(vrgc_c2_dict, vrc_c2_dict)
    ensure_vrgc_exists(args.c2_kubeconfig, args.c2_name, vrgc_c2_dict, temp_vrgc_path)


# --- Workload Deployment Functions ---

def update_appset_yaml(appset_data: List[Dict], args: argparse.Namespace, counter: int, workload_name: str, workload_dict: Dict, c1_dict: Dict, c2_dict: Dict, drpolicy_name: str) -> List[Dict]:
    """Update ApplicationSet YAML based on provided parameters."""
    logger.debug(f"Updating ApplicationSet YAML for {workload_name}")
    workload_cluster = args.deploy_on or random.choice([args.c1_name, args.c2_name])
    
    for item in appset_data:
        if item["kind"] == "ApplicationSet":
            item["metadata"]["name"] = workload_name
            item["spec"]["generators"][0]["clusterDecisionResource"]["labelSelector"]["matchLabels"]["cluster.open-cluster-management.io/placement"] = f"{workload_name}-placs"
            item["spec"]["template"]["metadata"]["name"] = f"{workload_name}-{{{{name}}}}"
            item["spec"]["template"]["spec"]["sources"][0]["path"] = workload_dict.get("workload_path")
            item["spec"]["template"]["spec"]["sources"][0]["repoURL"] = args.repo or DEFAULT_GIT_REPO
            item["spec"]["template"]["spec"]["sources"][0]["targetRevision"] = args.repo_branch if args.repo else DEFAULT_GIT_BRANCH
            item["spec"]["template"]["spec"]["destination"]["namespace"] = workload_name
        elif item["kind"] == "Placement":
            item["metadata"]["name"] = f"{workload_name}-placs"
            item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
            item["spec"]["clusterSets"][0] = args.clusterset
            if args.protect_workload == "yes":
                item["metadata"].setdefault("annotations", {}).setdefault("cluster.open-cluster-management.io/experimental-scheduling-disable", "true")
        elif item["kind"] == "DRPlacementControl" and args.protect_workload == "yes":
            item["metadata"]["name"] = f"{workload_name}-placs-drpc"
            item["spec"]["drPolicyRef"]["name"] = drpolicy_name
            item["spec"]["placementRef"]["name"] = f"{workload_name}-placs"
            item["spec"]["preferredCluster"] = workload_cluster
            pvc_sel = item["spec"]["pvcSelector"]["matchExpressions"][0]
            pvc_sel["key"] = workload_dict.get("workload_pvc_selector_key")
            pvc_sel["values"] = [workload_dict.get("workload_pvc_selector_value")]
            if args.cg:
                item["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")
    
    if workload_dict.get('workload') == "vm":
        if args.repo == DEFAULT_GIT_REPO:
            global VM_SECRET_REG_YAML, VM_REG_CERT_YAML
            VM_SECRET_REG_YAML = None
            VM_REG_CERT_YAML = None
        handle_vm_resources(c1_dict, c2_dict, workload_name, VM_SECRET_YAML, VM_SECRET_REG_YAML, VM_REG_CERT_YAML)
        
        
    return appset_data


def update_sub_yaml(sub_data: List[Dict], args: argparse.Namespace, counter: int, workload_name: str, workload_dict: Dict, c1_dict: Dict, c2_dict: Dict, drpolicy_name: str) -> List[Dict]:
    """Update Subscription YAML based on provided parameters."""
    logger.debug(f"Updating Subscription YAML for {workload_name}")
    channel = f"channel-{workload_name}" # Simpler channel name
    workload_cluster = args.deploy_on or random.choice([args.c1_name, args.c2_name])
    
    for item in sub_data:
        if item["kind"] == "Namespace":
            # This logic seems brittle, relies on template name.
            # Assuming first NS is workload, second is channel.
            if item["metadata"]["name"] == "sub-rbd-1":
                 item["metadata"]["name"] = workload_name
            else:
                 item["metadata"]["name"] = channel
        elif item["kind"] == "Application":
            item["metadata"]["name"] = item["metadata"]["namespace"] = workload_name
            item["spec"]["selector"]["matchExpressions"][0]["values"][0] = workload_name
        elif item["kind"] == "Channel":
            item["metadata"]["name"] = item["metadata"]["namespace"] = channel
            item["spec"]["pathname"] = args.repo
        elif item["kind"] == "Subscription":
            item["metadata"]["name"] = f"{workload_name}-sub"
            item["metadata"]["namespace"] = workload_name
            item["metadata"]["annotations"]["apps.open-cluster-management.io/git-branch"] = args.repo_branch if args.repo else DEFAULT_GIT_BRANCH
            item["metadata"]["annotations"]["apps.open-cluster-management.io/git-path"] = workload_dict.get("workload_path")
            item["metadata"]["labels"]["app"] = workload_name
            item["spec"]["channel"] = f"{channel}/{channel}"
            item["spec"]["placement"]["placementRef"]["name"] = f"{workload_name}-placs"
        elif item["kind"] == "Placement":
            item["metadata"]["labels"]["app"] = workload_name
            item["metadata"]["name"] = f"{workload_name}-placs"
            item["metadata"]["namespace"] = workload_name
            item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
            item["spec"]["clusterSets"][0] = args.clusterset
            if args.protect_workload == "yes":
                item["metadata"].setdefault("annotations", {}).setdefault("cluster.open-cluster-management.io/experimental-scheduling-disable", "true")
        elif item["kind"] == "ManagedClusterSetBinding":
            item["metadata"]["namespace"] = workload_name
            item["metadata"]["name"] = args.clusterset
            item["spec"]["clusterSet"] = args.clusterset
        elif item["kind"] == "DRPlacementControl" and args.protect_workload == "yes":
            item["metadata"]["name"] = f"{workload_name}-placs-drpc"
            item["metadata"]["namespace"] = workload_name
            item["spec"]["drPolicyRef"]["name"] = drpolicy_name
            item["spec"]["placementRef"]["name"] = f"{workload_name}-placs"
            item["spec"]["placementRef"]["namespace"] = workload_name
            item["spec"]["preferredCluster"] = workload_cluster
            pvc_sel = item["spec"]["pvcSelector"]["matchExpressions"][0]
            pvc_sel["key"] = workload_dict.get("workload_pvc_selector_key")
            pvc_sel["values"] = [workload_dict.get("workload_pvc_selector_value")]
            if args.cg:
                item["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")

    if workload_dict.get('workload') == "vm":
        if args.repo == DEFAULT_GIT_REPO:
            global VM_SECRET_REG_YAML, VM_REG_CERT_YAML
            VM_SECRET_REG_YAML = None
            VM_REG_CERT_YAML = None
        handle_vm_resources(c1_dict, c2_dict, workload_name, VM_SECRET_YAML, VM_SECRET_REG_YAML, VM_REG_CERT_YAML)
        
    return sub_data


def deploy_discovered_apps(args: argparse.Namespace, counter: int, workload_name: str, workload_dict: Dict, full_workload_path: Path, c1_dict: Dict, c2_dict: Dict, drpolicy_name: str) -> List[Dict]:
    """Deploy 'distributed' (discovered) apps using 'oc create -k'."""
    logger.info(f"Starting to deploy discovered app '{workload_name}'...")
    
    try:
        # Create the project on both clusters
        create_project(c1_dict["kubeconfig"], c1_dict["cluster_name"], workload_name)
        create_project(c2_dict["kubeconfig"], c2_dict["cluster_name"], workload_name)

        # Select cluster for deployment
        if args.deploy_on:
            deploy_cluster = c1_dict if args.c1_name == args.deploy_on else c2_dict
        else:
            deploy_cluster = random.choice([c1_dict, c2_dict])
        
        logger.info(f"Deploying workload to {deploy_cluster['cluster_name']} using kustomize path: {full_workload_path}")
        run_oc_command(["apply", "-k", str(full_workload_path), "--namespace", workload_name], deploy_cluster["kubeconfig"])
        logger.info(f"✅ Workload '{workload_name}' deployed.")
        
        output_yaml_docs = []

        if args.protect_workload == "yes":
            # Load templates
            placement_yaml_dict = load_yaml_file(PLACEMENT_YAML)[0]
            drpc_yaml_dict = load_yaml_file(DRPC_YAML)[0]

            # Update Placement
            placement_yaml_dict["metadata"]["name"] = f"{workload_name}-placs-1"
            placement_yaml_dict["metadata"]["namespace"] = "openshift-dr-ops" # TODO: Is this always correct?
            
            # Update DRPC
            drpc_yaml_dict["metadata"]["name"] = workload_name
            drpc_yaml_dict["spec"]["drPolicyRef"]["name"] = drpolicy_name
            drpc_yaml_dict["spec"]["placementRef"]["name"] = f"{workload_name}-placs-1"
            drpc_yaml_dict["spec"]["preferredCluster"] = deploy_cluster['cluster_name']
            drpc_yaml_dict["spec"]["protectedNamespaces"] = [workload_name]
            
            if not args.recipe:
                pvc_sel = drpc_yaml_dict["spec"]["pvcSelector"]["matchExpressions"][0]
                pvc_sel["key"] = workload_dict.get("workload_pvc_selector_key")
                pvc_sel["values"] = [workload_dict.get("workload_pvc_selector_value")]
                
                kube_sel = drpc_yaml_dict["spec"]["kubeObjectProtection"]["kubeObjectSelector"]["matchExpressions"][0]
                kube_sel["key"] = workload_dict.get("workload_pod_selector_key")
                kube_sel["values"] = [workload_dict.get("workload_pod_selector_value")]
            else:
                # Recipe-based protection
                drpc_yaml_dict["spec"]["pvcSelector"] = {} # Clear PVC selector
                kube_prot = drpc_yaml_dict["spec"]["kubeObjectProtection"]
                kube_prot.setdefault("recipeRef", {})["name"] = workload_name
                kube_prot["recipeRef"]["namespace"] = workload_name
                del kube_prot["kubeObjectSelector"]
            
            if args.cg:
                drpc_yaml_dict["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")
            
            output_yaml_docs.extend([placement_yaml_dict, drpc_yaml_dict])

            if args.recipe:
                recipe_yaml_dict = load_yaml_file(RECIPE_YAML)[0]
                recipe_yaml_dict["metadata"]["name"] = workload_name
                recipe_yaml_dict["spec"]["appType"] = workload_dict.get('workload')
                
                group = recipe_yaml_dict["spec"]["groups"][0]
                group["backupRef"] = workload_name
                group["includedNamespaces"] = [workload_name]
                group["name"] = workload_name
                group_sel = group["labelSelector"]["matchExpressions"][0]
                group_sel["key"] = workload_dict.get("workload_pod_selector_key")
                group_sel["values"] = [workload_dict.get("workload_pod_selector_value")]
                
                recipe_yaml_dict["spec"]["workflows"][0]["sequence"][1]["group"] = workload_name
                recipe_yaml_dict["spec"]["workflows"][1]["sequence"][0]["group"] = workload_name
                recipe_yaml_dict["spec"]["hooks"][0]["namespace"] = workload_name
                recipe_yaml_dict["spec"]["hooks"][0]["nameSelector"] = f"{workload_dict.get('workload')}-*"
                
                vol_spec = recipe_yaml_dict["spec"]["volumes"]
                vol_spec["includedNamespaces"] = [workload_name]
                vol_sel = vol_spec["labelSelector"]["matchExpressions"][0]
                vol_sel["key"] = workload_dict.get("workload_pvc_selector_key")
                vol_sel["values"] = [workload_dict.get("workload_pvc_selector_value")]
                
                # Create recipe on both clusters
                temp_recipe_path = SCRIPT_DIR / f"temp-recipe-{workload_name}.yaml"
                write_output_yaml([recipe_yaml_dict], temp_recipe_path)
                create_resource(c1_dict["kubeconfig"], c1_dict["cluster_name"], temp_recipe_path, "recipe")
                create_resource(c2_dict["kubeconfig"], c2_dict["cluster_name"], temp_recipe_path, "recipe")
                temp_recipe_path.unlink()
                
                output_yaml_docs.append(recipe_yaml_dict)

        if workload_dict.get('workload') == "vm":
            if not args.git_token:
                global VM_SECRET_REG_YAML, VM_REG_CERT_YAML
                VM_SECRET_REG_YAML = None
                VM_REG_CERT_YAML = None

            handle_vm_resources(c1_dict, c2_dict, workload_name, VM_SECRET_YAML, VM_SECRET_REG_YAML, VM_REG_CERT_YAML)

        logger.info(f"✅ Deployment and protection setup for '{workload_name}' completed.")
        return output_yaml_docs
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ An error occurred during workload deployment for '{workload_name}': {e.stderr}")
        raise
    except Exception as e:
        logger.error(f"❌ A critical error occurred for '{workload_name}': {e}")
        raise


# --- Main Execution ---

def main():
    """Main function to execute workload deployment."""
    args = parse_args()
    
    # --- Set Log Level ---
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled.")
    else:
        logger.setLevel(logging.INFO)
        
    logger.debug(f"Script arguments loaded: {vars(args)}")

    # --- Manual Arg Validation ---
    # We do this here because we removed 'required=True' from argparse
    # to support loading from a config file.
    required_args = [
        'workload_pvc_type', 'workload_type', 'workload_count', 
        'output_dir', 'protect_workload', 'c1_name', 'c1_kubeconfig',
        'c2_name', 'c2_kubeconfig'
    ]
    
    missing_args = [arg for arg in required_args if getattr(args, arg) is None]
    
    if missing_args:
        logger.error(f"❌ Missing required arguments: {', '.join(missing_args)}")
        logger.error("Please provide them via command line or a -config file.")
        sys.exit(1)

    # --- Pre-flight Validations ---
    args.output_dir_path.mkdir(parents=True, exist_ok=True)
    
    if args.cg and args.workload_pvc_type == "cephfs":
        logger.error("❌ Cephfs with CG is not supported.")
        sys.exit(1)
    if args.workload_pvc_type == "cephfs" and args.workload == "vm":
        logger.error("❌ 'vm' workload is not supported with 'cephfs' PVC type.")
        sys.exit(1)
    if args.recipe and args.workload_type in ("appset", "sub"):
        logger.error(f"❌ 'recipe' does not work with {args.workload_type}.")
        sys.exit(1)

    # --- Initial Setup ---
    if args.cg:
        create_vrgc_on_clusters(args)
    
    workload_dict = get_workload_details(args.workload_pvc_type, args.workload)
    
    # Load templates or clone repo *once* before the loop
    template_data: Optional[List[Dict]] = None
    full_workload_path: Optional[Path] = None
    
    if args.workload_type != "dist":
        yaml_file = WORKLOAD_DATA_DIR / f"sample_{args.workload_type}_rbd.yaml"
        template_data = load_yaml_file(yaml_file)
    else:
        git_repo = args.repo or DEFAULT_GIT_REPO
        git_branch = args.repo_branch if args.repo else DEFAULT_GIT_BRANCH
        clone_path = SCRIPT_DIR / CLONE_DIR_NAME
        if args.git_token:
            git_repo = git_repo.replace("https://", f"https://{args.git_token}@")
        
        clone_and_checkout(git_repo, clone_path, git_branch)
        full_workload_path = clone_path / workload_dict.get("workload_path")
        if not full_workload_path.exists():
            logger.error(f"❌ Workload path not found in cloned repo: {full_workload_path}")
            sys.exit(1)

    # --- Cluster & Policy Setup ---
    all_output_yaml: List[Dict] = []
    c1_dict = {"cluster_name": args.c1_name, "kubeconfig": args.c1_kubeconfig}
    c2_dict = {"cluster_name": args.c2_name, "kubeconfig": args.c2_kubeconfig}

    if not args.drpolicy_name:
        logger.debug("No DRPolicy specified, attempting to find one...")
        try:
            result = run_oc_command(["get", "drpolicy", "--no-headers"])
            policy_names = [line.split()[0] for line in result.stdout.strip().split('\n') if line.strip()]
            if not policy_names:
                logger.error("❌ No DRPolicies found in the cluster.")
                sys.exit(1)
            logger.debug(f"Found DRPolicies: {policy_names}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to list DRPolicies: {e.stderr}")
            sys.exit(1)
    else:
        validate_drpolicy(args.drpolicy_name)
        policy_names = [args.drpolicy_name]

    args.clusterset = args.clusterset or get_clusterset_name(args.c1_name)
    if not args.clusterset:
        logger.error(f"❌ Could not determine clusterset for {args.c1_name}")
        sys.exit(1)
        
    current_count = get_existing_workload_count(args.workload_type, args.workload_pvc_type, args.workload, args.cg, args.c1_kubeconfig)

    # --- Main Deployment Loop ---
    logger.info(f"Starting deployment of {args.workload_count} workload(s)...")
    
    for i in range(1, args.workload_count + 1):
        dynamic_i = current_count + i
        policy_name = random.choice(policy_names)
        
        workload_name = generate_workload_name(
            args.workload_type, args.workload, args.workload_pvc_type, 
            dynamic_i, args.ns_dr_prefix, args.cg, args.recipe
        )
        logger.info(f"--- Processing workload {i}/{args.workload_count} (Name: {workload_name}) ---")

        try:
            updated_yaml: Optional[List[Dict]] = None
            if args.workload_type == "appset":
                # Deep copy data to avoid modifying template in-memory
                data_copy = copy.deepcopy(template_data)
                updated_yaml = update_appset_yaml(data_copy, args, dynamic_i, workload_name, workload_dict, c1_dict, c2_dict, policy_name)

            elif args.workload_type == "sub":
                data_copy = copy.deepcopy(template_data)
                updated_yaml = update_sub_yaml(data_copy, args, dynamic_i, workload_name, workload_dict, c1_dict, c2_dict, policy_name)
            
            else: # dist
                updated_yaml = deploy_discovered_apps(args, dynamic_i, workload_name, workload_dict, full_workload_path, c1_dict, c2_dict, policy_name)
            
            if updated_yaml:
                all_output_yaml.extend(updated_yaml)
                
        except Exception as e:
            logger.error(f"❌ Failed to process workload {workload_name}: {e}. Skipping...")
            # Continue to next iteration


    # --- Write Combined Output ---
    if all_output_yaml:
        ns_prefix = f"{args.ns_dr_prefix}_" if args.ns_dr_prefix else ""
        file_name = f"output_{ns_prefix}{args.workload_type}_{args.workload_pvc_type}_{args.workload}_combined.yaml"
        single_output_file = args.output_dir_path / file_name
        
        logger.info(f"Writing combined YAML to: {single_output_file}")
        write_output_yaml(all_output_yaml, single_output_file)
    else:
        logger.warning("⚠ No YAML documents were generated to write.")

    logger.info("✅ Script execution finished.")

if __name__ == "__main__":
    main()