#!/usr/bin/env python3

"""
Enhanced Workload Deployment Script with Multi-Namespace Support

Key Feature: -multi_ns_workload parameter allows deploying multiple workloads
in separate namespaces on the SAME cluster.

Example: -multi_ns_workload 2 creates:
  - imp-busybox-rbd-multi-1-1 (on cluster1)
  - imp-busybox-rbd-multi-1-2 (on cluster1)
Both workloads deployed on the same cluster with DR protection.
"""

import argparse
import copy
import json
import logging
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# --- Configuration ---

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
WORKLOAD_DATA_DIR = SCRIPT_DIR / "workload_data"
OUTPUT_DATA_DIR = SCRIPT_DIR / "output_data"
CLONE_DIR_NAME = "ocs-workloads"
OC_CMD = "oc"

DEFAULT_GIT_REPO = "https://github.com/red-hat-storage/ocs-workloads.git"
DEFAULT_GIT_BRANCH = "master"


# --- Enums ---

class WorkloadType(Enum):
    """Workload deployment types."""
    APPSET = "appset"
    SUBSCRIPTION = "sub"
    DISCOVERED = "dist"


class ClusterSelectionStrategy(Enum):
    """Strategy for selecting target cluster."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_LOADED = "least_loaded"
    SPECIFIED = "specified"


# --- Data Classes ---

@dataclass
class ClusterConfig:
    """Configuration for a cluster."""
    name: str
    kubeconfig: str
    workload_count: int = 0  # Track deployed workloads


@dataclass
class WorkloadDetails:
    """Details about a workload type."""
    path: str
    workload: str
    pod_selector_key: str
    pod_selector_value: str
    pvc_selector_key: str
    pvc_selector_value: str


@dataclass
class DeploymentResult:
    """Result of a workload deployment."""
    success: bool
    workload_name: str
    namespace: str
    cluster_name: str
    error_message: Optional[str] = None
    yaml_docs: List[Dict] = field(default_factory=list)
    multi_ns_index: Optional[int] = None  # Track multi-ns workload index


@dataclass
class DeploymentConfig:
    """Configuration for workload deployment."""
    workload_pvc_type: str
    workload_type: str
    workload_count: int
    deploy_on: Optional[str]
    output_dir_path: Path
    protect_workload: str
    drpolicy_name: Optional[str]
    cg: bool
    workload: str
    ns_dr_prefix: Optional[str]
    recipe: bool
    repo: Optional[str]
    repo_branch: str
    git_token: Optional[str]
    clusterset: Optional[str]
    cluster1: ClusterConfig
    cluster2: ClusterConfig
    selection_strategy: ClusterSelectionStrategy = ClusterSelectionStrategy.ROUND_ROBIN
    multi_ns_workload: int = 1  # Number of namespaces per workload
    vm_type: str = "vm-pvc"  # VM workload type (vm-pvc, vm-dv, vm-dvt)


# --- Argument Parsing ---

class ConfigLoader:
    """Handles loading configuration from files and command line."""
    
    @staticmethod
    def parse_args() -> argparse.Namespace:
        """Parse command-line arguments and optionally load from config file."""
        parser = argparse.ArgumentParser(
            description='Deploy workloads to OCP clusters for DR testing.',
            formatter_class=argparse.RawTextHelpFormatter
        )
        
        ConfigLoader._add_arguments(parser)
        
        # Parse once to get config file path
        known_args, _ = parser.parse_known_args()
        
        # Load config file if provided
        config_data = ConfigLoader._load_config_file(known_args.config)
        
        # Set defaults from config and parse again
        parser.set_defaults(**config_data)
        args = parser.parse_args()
        
        # Post-process arguments
        ConfigLoader._post_process_args(args)
        
        return args
    
    @staticmethod
    def _add_arguments(parser: argparse.ArgumentParser) -> None:
        """Add all command-line arguments to parser."""
        # Config/Verbose
        parser.add_argument(
            '-config', type=Path,
            help='Path to a config.yaml file. CLI args override config values.'
        )
        parser.add_argument(
            '-v', '--verbose', action='store_true',
            help='Enable DEBUG level logging'
        )
        
        # Cluster configuration
        parser.add_argument('-clusterset', type=str, help='Cluster set name')
        parser.add_argument('-c1_name', type=str, help='Cluster 1 name')
        parser.add_argument('-c1_kubeconfig', type=str, help='Cluster 1 Kubeconfig')
        parser.add_argument('-c2_name', type=str, help='Cluster 2 name')
        parser.add_argument('-c2_kubeconfig', type=str, help='Cluster 2 Kubeconfig')
        
        # Workload configuration
        parser.add_argument(
            '-workload_pvc_type', type=str,
            choices=['rbd', 'cephfs', 'mix'],
            help='Workload PVC type'
        )
        parser.add_argument(
            '-workload_type', type=str,
            choices=['appset', 'sub', 'dist'],
            help='Workload type'
        )
        parser.add_argument(
            '-workload_count', type=int,
            help='Number of workloads to deploy'
        )
        parser.add_argument(
            '-workload', type=str, default="busybox",
            choices=['busybox', 'vm', 'mysql'],
            help='Workload to deploy'
        )
        parser.add_argument(
            '-vm_type', type=str, default="vm-pvc",
            choices=['vm-pvc', 'vm-dv', 'vm-dvt'],
            help='VM workload type (only applicable when -workload vm): vm-pvc, vm-dv, or vm-dvt (default: vm-pvc)'
        )
        
        # Multi-namespace workload support
        parser.add_argument(
            '-multi_ns_workload', type=int, default=1,
            help='Number of namespaces to create per workload on same cluster (default: 1). '
                 'Example: -multi_ns_workload 2 creates imp-rbd-multi-1-1 and imp-rbd-multi-1-2 on same cluster'
        )
        
        # Deployment options
        parser.add_argument(
            '-deploy_on', type=str,
            help='Deploy workload on specific cluster'
        )
        parser.add_argument(
            '-output_dir', type=str,
            help='Directory for output YAML files'
        )
        parser.add_argument(
            '-protect_workload', type=str,
            choices=['yes', 'no'],
            help='Protect the workload'
        )
        parser.add_argument('-drpolicy_name', type=str, help='DR Policy name')
        parser.add_argument(
            '-cg', action='store_true',
            help='Enable Consistency Group'
        )
        parser.add_argument(
            '-ns_dr_prefix', type=str,
            help='Prefix for namespaces'
        )
        parser.add_argument(
            '-recipe', action='store_true',
            help='Protect discovered workload using recipe'
        )
        
        # Git configuration
        parser.add_argument('-repo', type=str, help='Repo for dist workloads')
        parser.add_argument(
            '-repo_branch', type=str, default=DEFAULT_GIT_BRANCH,
            help='Branch to use for repo'
        )
        parser.add_argument('-git_token', type=str, help='Token for git clone')
        
        # Cluster selection strategy
        parser.add_argument(
            '-cluster_strategy', type=str,
            choices=['round_robin', 'random', 'least_loaded'],
            default='round_robin',
            help='Strategy for selecting target cluster for dist workloads (default: round_robin)'
        )
    
    @staticmethod
    def _load_config_file(config_path: Optional[Path]) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not config_path:
            return {}
        
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return {}
        
        logger.info(f"Loading config from {config_path}")
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    
    @staticmethod
    def _post_process_args(args: argparse.Namespace) -> None:
        """Post-process parsed arguments."""
        if args.workload_pvc_type == "mix":
            args.workload_pvc_type = "mix-workload"
        
        if args.output_dir:
            args.output_dir_path = SCRIPT_DIR / OUTPUT_DATA_DIR / args.output_dir
        else:
            args.output_dir_path = None
        
        # Validate multi_ns_workload
        if args.multi_ns_workload < 1:
            logger.error("❌ -multi_ns_workload must be at least 1")
            sys.exit(1)


# --- Validation ---

class ConfigValidator:
    """Validates deployment configuration."""
    
    REQUIRED_ARGS = [
        'workload_pvc_type', 'workload_type', 'workload_count',
        'output_dir', 'protect_workload', 'c1_name', 'c1_kubeconfig',
        'c2_name', 'c2_kubeconfig'
    ]
    
    @staticmethod
    def validate(args: argparse.Namespace) -> None:
        """Validate all configuration requirements."""
        ConfigValidator._check_required_args(args)
        ConfigValidator._check_compatibility(args)
        ConfigValidator._ensure_output_dir(args)
    
    @staticmethod
    def _check_required_args(args: argparse.Namespace) -> None:
        """Check that all required arguments are provided."""
        missing = [
            arg for arg in ConfigValidator.REQUIRED_ARGS
            if getattr(args, arg) is None
        ]
        
        if missing:
            logger.error(f"❌ Missing required arguments: {', '.join(missing)}")
            logger.error("Provide them via command line or -config file.")
            sys.exit(1)
    
    @staticmethod
    def _check_compatibility(args: argparse.Namespace) -> None:
        """Check for incompatible configuration combinations."""
        if args.cg and args.workload_pvc_type == "cephfs":
            logger.error("❌ CephFS with CG is not supported.")
            sys.exit(1)
        
        if args.workload_pvc_type == "cephfs" and args.workload == "vm":
            logger.error("❌ VM workload not supported with CephFS.")
            sys.exit(1)
        
        if args.recipe and args.workload_type in ("appset", "sub"):
            logger.error(f"❌ Recipe does not work with {args.workload_type}.")
            sys.exit(1)
        
        # Validate deploy_on cluster name if specified
        if args.deploy_on and args.deploy_on not in [args.c1_name, args.c2_name]:
            logger.error(f"❌ Invalid deploy_on cluster: {args.deploy_on}. Must be {args.c1_name} or {args.c2_name}")
            sys.exit(1)
        
        # Validate multi_ns_workload with workload_type
        if args.multi_ns_workload > 1 and args.workload_type != "dist":
            logger.error("❌ -multi_ns_workload is only supported with -workload_type dist")
            sys.exit(1)
    
    @staticmethod
    def _ensure_output_dir(args: argparse.Namespace) -> None:
        """Ensure output directory exists."""
        args.output_dir_path.mkdir(parents=True, exist_ok=True)


# --- Cluster Selection ---

class ClusterSelector:
    """Handles cluster selection logic for distributed workloads."""
    
    def __init__(
        self,
        cluster1: ClusterConfig,
        cluster2: ClusterConfig,
        strategy: ClusterSelectionStrategy,
        specified_cluster: Optional[str] = None
    ):
        self.cluster1 = cluster1
        self.cluster2 = cluster2
        self.strategy = strategy
        self.specified_cluster = specified_cluster
        self._round_robin_counter = 0
    
    def select_cluster(self) -> ClusterConfig:
        """Select cluster based on configured strategy."""
        if self.specified_cluster:
            cluster = self._get_cluster_by_name(self.specified_cluster)
            logger.debug(f"Using specified cluster: {cluster.name}")
            return cluster
        
        if self.strategy == ClusterSelectionStrategy.ROUND_ROBIN:
            return self._select_round_robin()
        elif self.strategy == ClusterSelectionStrategy.RANDOM:
            return self._select_random()
        elif self.strategy == ClusterSelectionStrategy.LEAST_LOADED:
            return self._select_least_loaded()
        else:
            return self._select_round_robin()
    
    def _select_round_robin(self) -> ClusterConfig:
        """Select cluster using round-robin strategy."""
        cluster = self.cluster1 if self._round_robin_counter % 2 == 0 else self.cluster2
        self._round_robin_counter += 1
        logger.debug(f"Round-robin selected: {cluster.name}")
        return cluster
    
    def _select_random(self) -> ClusterConfig:
        """Select cluster randomly."""
        cluster = random.choice([self.cluster1, self.cluster2])
        logger.debug(f"Randomly selected: {cluster.name}")
        return cluster
    
    def _select_least_loaded(self) -> ClusterConfig:
        """Select cluster with fewer workloads."""
        if self.cluster1.workload_count <= self.cluster2.workload_count:
            cluster = self.cluster1
        else:
            cluster = self.cluster2
        logger.debug(f"Least loaded selected: {cluster.name} (count: {cluster.workload_count})")
        return cluster
    
    def _get_cluster_by_name(self, name: str) -> ClusterConfig:
        """Get cluster configuration by name."""
        if self.cluster1.name == name:
            return self.cluster1
        elif self.cluster2.name == name:
            return self.cluster2
        else:
            raise ValueError(f"Unknown cluster name: {name}")


# --- Workload Details ---

class WorkloadManager:
    """Manages workload configurations and naming."""
    
    @staticmethod
    def get_details(pvc_type: str, workload: str, vm_type: str = "vm-pvc") -> WorkloadDetails:
        """Get workload details based on PVC type and workload."""
        logger.debug(f"Getting workload details: pvc_type={pvc_type}, workload={workload}, vm_type={vm_type}")
        
        if workload == "busybox":
            return WorkloadManager._get_busybox_details(pvc_type)
        elif workload == "vm":
            return WorkloadManager._get_vm_details(vm_type)
        else:  # mysql
            return WorkloadManager._get_mysql_details(pvc_type)
    
    @staticmethod
    def _get_busybox_details(pvc_type: str) -> WorkloadDetails:
        """Get busybox workload details."""
        if pvc_type == "mix-workload":
            return WorkloadDetails(
                path="rdr/busybox/mix-workload/workloads/app-busybox-1",
                workload="busybox",
                pod_selector_key="workloadpattern",
                pod_selector_value="simple_io",
                pvc_selector_key="appname",
                pvc_selector_value="busybox_app_mix"
            )
        else:
            return WorkloadDetails(
                path=f"rdr/busybox/{pvc_type}/workloads/app-busybox-1",
                workload="busybox",
                pod_selector_key="workloadpattern",
                pod_selector_value="simple_io",
                pvc_selector_key="workloadpattern",
                pvc_selector_value="simple_io_pvc"
            )
    
    @staticmethod
    def _get_vm_details(vm_type: str) -> WorkloadDetails:
        """Get VM workload details."""
        return WorkloadDetails(
            path=f"rdr/cnv-workload/{vm_type}/vm-resources/vm-workload-1",
            workload="vm",
            pod_selector_key="appname",
            pod_selector_value="kubevirt",
            pvc_selector_key="appname",
            pvc_selector_value="kubevirt"
        )
    
    @staticmethod
    def _get_mysql_details(pvc_type: str) -> WorkloadDetails:
        """Get MySQL workload details."""
        return WorkloadDetails(
            path=f"rdr/mysql/{pvc_type}/workloads/app-mysql-1",
            workload="mysql",
            pod_selector_key="appname",
            pod_selector_value="mysql_app_1",
            pvc_selector_key="workloadpattern",
            pvc_selector_value="mysql_io_pvc"
        )
    
    @staticmethod
    def generate_name(
        workload_type: str,
        workload: str,
        pvc_type: str,
        counter: int,
        ns_dr_prefix: Optional[str] = None,
        cg: bool = False,
        recipe: bool = False,
        multi_ns_index: Optional[int] = None
    ) -> str:
        """Generate a standardized workload/namespace name."""
        # Determine type prefix
        type_prefix = {
            "appset": "app",
            "sub": "sub",
            "dist": "imp"
        }.get(workload_type, "imp")
        
        # Handle CG naming
        workload_short = workload
        if cg:
            workload_short = {"busybox": "bb", "mysql": "my"}.get(workload, workload)
            if workload_type in ("appset", "sub"):
                type_prefix = "ap"
        
        # Build name components
        ns_prefix = f"{ns_dr_prefix}-" if ns_dr_prefix else ""
        recipe_prefix = "rp-" if recipe else ""
        cg_suffix = "-cg" if cg else ""
        
        # Add multi-ns suffix if applicable
        multi_suffix = ""
        if multi_ns_index is not None:
            multi_suffix = f"-multi-{counter}-{multi_ns_index}"
            name = f"{ns_prefix}{type_prefix}-{workload_short}-{pvc_type}{multi_suffix}{cg_suffix}"
        else:
            name = f"{ns_prefix}{type_prefix}-{workload_short}-{pvc_type}-{recipe_prefix}{counter}{cg_suffix}"
        
        logger.debug(f"Generated workload name: {name}")
        return name


# --- YAML Utilities ---

class YAMLHelper:
    """Helper class for YAML file operations."""
    
    @staticmethod
    def load(filepath: Path) -> List[Dict[str, Any]]:
        """Load YAML content from file."""
        logger.debug(f"Loading YAML: {filepath}")
        try:
            with open(filepath, 'r') as file:
                return list(yaml.safe_load_all(file))
        except FileNotFoundError:
            logger.error(f"❌ YAML file not found: {filepath}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Failed to load YAML {filepath}: {e}")
            sys.exit(1)
    
    @staticmethod
    def write(data: List[Dict[str, Any]], output_path: Path) -> None:
        """Write YAML data to file."""
        logger.debug(f"Writing {len(data)} YAML documents to {output_path}")
        try:
            with open(output_path, 'w') as outfile:
                if data:
                    yaml.dump_all(data, outfile, sort_keys=False, indent=2)
                else:
                    logger.warning(f"⚠ No data to write to {output_path}")
        except Exception as e:
            logger.error(f"❌ Failed to write YAML to {output_path}: {e}")


# --- Git Operations ---

class GitHelper:
    """Helper class for Git operations."""
    
    @staticmethod
    def clone_and_checkout(repo_url: str, clone_path: Path, branch: str) -> None:
        """Clone repository and checkout specified branch."""
        GitHelper._cleanup_existing(clone_path)
        GitHelper._clone(repo_url, clone_path, branch)
    
    @staticmethod
    def _cleanup_existing(clone_path: Path) -> None:
        """Remove existing clone directory."""
        if clone_path.exists():
            logger.info(f"Removing existing directory: {clone_path}")
            try:
                shutil.rmtree(clone_path)
            except OSError as e:
                logger.error(f"❌ Failed to remove {clone_path}: {e}")
                sys.exit(1)
    
    @staticmethod
    def _clone(repo_url: str, clone_path: Path, branch: str) -> None:
        """Clone the repository."""
        try:
            logger.info(f"Cloning {repo_url} (branch: {branch})")
            result = subprocess.run(
                ["git", "clone", "--quiet", "--branch", branch, repo_url, str(clone_path)],
                check=True,
                capture_output=True,
                text=True
            )
            logger.debug(f"Git stdout: {result.stdout}")
            logger.info("✅ Repository cloned successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to clone repository: {e.stderr}")
            sys.exit(1)


# --- OpenShift Command Wrapper ---

class OpenShiftClient:
    """Wrapper for OpenShift CLI operations."""
    
    @staticmethod
    def run_command(
        cmd_args: List[str],
        kubeconfig: Optional[str] = None,
        check: bool = True
    ) -> subprocess.CompletedProcess:
        """Execute an 'oc' command."""
        base_cmd = [OC_CMD]
        if kubeconfig:
            base_cmd.extend(["--kubeconfig", str(kubeconfig)])
        base_cmd.extend(cmd_args)
        
        logger.debug(f"Running: {' '.join(base_cmd)}")
        result = subprocess.run(
            base_cmd,
            capture_output=True,
            text=True,
            check=check
        )
        
        if result.stderr and check:
            logger.debug(f"stderr: {result.stderr.strip()}")
        if result.stdout:
            logger.debug(f"stdout: {result.stdout.strip()}")
        
        return result
    
    @staticmethod
    def create_project(cluster: ClusterConfig, project_name: str) -> None:
        """Create a project if it doesn't exist."""
        try:
            OpenShiftClient.run_command(
                ["new-project", project_name],
                cluster.kubeconfig
            )
            logger.info(f"✅ Project '{project_name}' created on {cluster.name}")
        except subprocess.CalledProcessError as e:
            if "already exists" in e.stderr:
                logger.info(f"⚠ Project '{project_name}' exists on {cluster.name}")
            else:
                logger.error(f"❌ Failed to create project '{project_name}': {e.stderr}")
                raise
    
    @staticmethod
    def apply_kustomize(
        cluster: ClusterConfig,
        kustomize_path: Path,
        namespace: str
    ) -> None:
        """Apply kustomize configuration to a namespace."""
        try:
            logger.info(f"Applying kustomize from {kustomize_path} to {namespace} on {cluster.name}")
            OpenShiftClient.run_command(
                ["apply", "-k", str(kustomize_path), "--namespace", namespace],
                cluster.kubeconfig
            )
            logger.info(f"✅ Workload deployed to {namespace} on {cluster.name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to apply kustomize: {e.stderr}")
            raise
    
    @staticmethod
    def create_resource(
        cluster: ClusterConfig,
        yaml_file: Path,
        resource_label: str
    ) -> None:
        """Create a resource from YAML file."""
        try:
            OpenShiftClient.run_command(
                ["create", "-f", str(yaml_file)],
                cluster.kubeconfig
            )
            logger.info(f"✅ Created {resource_label} on {cluster.name}")
        except subprocess.CalledProcessError as e:
            if "AlreadyExists" in e.stderr or "already exists" in e.stderr:
                logger.info(f"⚠ {resource_label} exists on {cluster.name}")
            else:
                logger.error(f"❌ Failed to create {resource_label}: {e.stderr}")
                raise
    
    @staticmethod
    def get_clusterset_name(cluster_name: str) -> Optional[str]:
        """Get clusterset name for a cluster."""
        logger.debug(f"Getting clusterset for {cluster_name}")
        try:
            result = OpenShiftClient.run_command(
                ["get", "managedcluster", cluster_name, "-o", "yaml"]
            )
            data = yaml.safe_load(result.stdout)
            clusterset = data.get("metadata", {}).get("labels", {}).get(
                "cluster.open-cluster-management.io/clusterset"
            )
            logger.debug(f"Found clusterset: {clusterset}")
            return clusterset
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to get clusterset: {e.stderr}")
            sys.exit(1)
    
    @staticmethod
    def validate_drpolicy(drpolicy_name: str) -> None:
        """Validate that DRPolicy exists."""
        logger.debug(f"Validating DRPolicy: {drpolicy_name}")
        try:
            OpenShiftClient.run_command(["get", "drpolicy", drpolicy_name])
            logger.info(f"✅ DRPolicy '{drpolicy_name}' validated")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ DRPolicy '{drpolicy_name}' not found: {e.stderr}")
            sys.exit(1)
    
    @staticmethod
    def get_existing_workload_count(
        workload_type: str,
        pvc_type: str,
        workload: str,
        cg: bool,
        kubeconfig: str
    ) -> int:
        """Get count of existing workloads."""
        logger.debug("Getting existing workload count...")
        try:
            if workload_type == "appset":
                resource = "ApplicationSet.argoproj.io"
                cmd_args = ["get", resource, "-A", "-o", "name"]
            elif workload_type == "sub":
                resource = "Subscription.apps.open-cluster-management.io"
                cmd_args = ["get", resource, "-A", "-o", "name"]
            else:  # dist
                resource = "namespace"
                cmd_args = ["get", resource, "--no-headers", "-o", "name", "--kubeconfig", kubeconfig]
            
            result = OpenShiftClient.run_command(cmd_args)
            
            # Adjust search terms for CG
            search_workload = workload
            if cg and workload_type in ("appset", "sub"):
                search_workload = {"busybox": "bb", "mysql": "my"}.get(workload, workload)
            
            search_prefix = "imp-" if workload_type == "dist" else ""
            
            count = sum(
                1 for line in result.stdout.splitlines()
                if search_prefix in line and pvc_type in line and search_workload in line
            )
            
            logger.info(f"Found {count} existing '{workload_type}' workloads")
            return count
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to count existing workloads: {e.stderr}")
            return 0


# --- VM Resource Management ---

class VMResourceManager:
    """Manages VM-specific resources."""
    
    @staticmethod
    def setup_vm_resources(
        cluster1: ClusterConfig,
        cluster2: ClusterConfig,
        namespace: str,
        use_default_repo: bool
    ) -> None:
        """Set up VM resources for both clusters."""
        logger.info(f"Setting up VM resources for namespace '{namespace}'...")
        
        # Create projects
        OpenShiftClient.create_project(cluster1, namespace)
        OpenShiftClient.create_project(cluster2, namespace)
        
        # Create secrets
        VMResourceManager._create_vm_secrets(
            cluster1, cluster2, namespace, use_default_repo
        )
    
    @staticmethod
    def _create_vm_secrets(
        cluster1: ClusterConfig,
        cluster2: ClusterConfig,
        namespace: str,
        use_default_repo: bool
    ) -> None:
        """Create VM secrets on both clusters."""
        secret_files = [WORKLOAD_DATA_DIR / "vm-secret.yaml"]
        
        if not use_default_repo:
            secret_files.extend([
                WORKLOAD_DATA_DIR / "vm-secret-reg.yaml",
                WORKLOAD_DATA_DIR / "vm-reg-cert.yaml"
            ])
        
        for secret_file in secret_files:
            if not secret_file.exists():
                continue
            
            # Load and update secret
            secret_data = YAMLHelper.load(secret_file)[0]
            secret_data["metadata"]["namespace"] = namespace
            
            # Write temporary file
            temp_path = OUTPUT_DATA_DIR / f"temp-{secret_file.stem}-{namespace}.yaml"
            YAMLHelper.write([secret_data], temp_path)
            
            # Create on both clusters
            OpenShiftClient.create_resource(
                cluster1, temp_path, f"{secret_file.stem} in {namespace}"
            )
            OpenShiftClient.create_resource(
                cluster2, temp_path, f"{secret_file.stem} in {namespace}"
            )
            
            # Cleanup
            temp_path.unlink()


# --- Distributed Workload Deployer ---

class DistributedWorkloadDeployer:
    """
    Specialized deployer for distributed (discovered) workloads.
    Supports multi-namespace workload deployment on same cluster.
    """
    
    def __init__(
        self,
        config: DeploymentConfig,
        workload_details: WorkloadDetails,
        cluster_selector: ClusterSelector,
        kustomize_path: Path
    ):
        self.config = config
        self.workload_details = workload_details
        self.cluster_selector = cluster_selector
        self.kustomize_path = kustomize_path
    
    def deploy(
        self,
        base_workload_name: str,
        counter: int,
        policy_name: str
    ) -> List[DeploymentResult]:
        """
        Deploy workload with support for multi-namespace deployment.
        
        Returns list of DeploymentResult, one per namespace created.
        """
        results = []
        all_namespaces = []  # Track all namespaces in this group
        
        # Select target cluster (same cluster for all multi-ns workloads)
        target_cluster = self.cluster_selector.select_cluster()
        logger.info(f"📍 Selected cluster: {target_cluster.name} for workload group {counter}")
        
        # Deploy to multiple namespaces if multi_ns_workload > 1
        for ns_index in range(1, self.config.multi_ns_workload + 1):
            # Generate namespace name
            if self.config.multi_ns_workload > 1:
                workload_name = WorkloadManager.generate_name(
                    self.config.workload_type,
                    self.config.workload,
                    self.config.workload_pvc_type,
                    counter,
                    self.config.ns_dr_prefix,
                    self.config.cg,
                    self.config.recipe,
                    multi_ns_index=ns_index
                )
            else:
                workload_name = base_workload_name
            
            all_namespaces.append(workload_name)
            logger.info(f"🚀 Deploying to namespace: {workload_name} on {target_cluster.name}")
            
            try:
                # Create namespaces on both clusters (for DR)
                self._create_namespaces(workload_name)
                
                # Deploy workload to ONLY the selected cluster
                self._deploy_to_cluster(target_cluster, workload_name)
                
                # Setup VM resources if needed
                if self.workload_details.workload == "vm":
                    self._setup_vm_resources(workload_name)
                
                logger.info(f"✅ Successfully deployed '{workload_name}' to {target_cluster.name}")
                
                results.append(DeploymentResult(
                    success=True,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name=target_cluster.name,
                    yaml_docs=[],  # DR resources created once per group below
                    multi_ns_index=ns_index if self.config.multi_ns_workload > 1 else None
                ))
                
            except Exception as e:
                logger.error(f"❌ Failed to deploy '{workload_name}': {e}")
                results.append(DeploymentResult(
                    success=False,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name=target_cluster.name,
                    error_message=str(e),
                    multi_ns_index=ns_index if self.config.multi_ns_workload > 1 else None
                ))
        
        # Create DR resources ONCE for ALL namespaces in the group
        if self.config.protect_workload == "yes" and all_namespaces:
            try:
                logger.info(f"🔒 Creating DR protection for {len(all_namespaces)} namespace(s)")
                yaml_docs = self._create_dr_resources_for_group(
                    all_namespaces,
                    counter,
                    target_cluster,
                    policy_name
                )
                # Add DR resources to first successful result
                for result in results:
                    if result.success:
                        result.yaml_docs = yaml_docs
                        break
            except Exception as e:
                logger.error(f"❌ Failed to create DR resources: {e}")
        
        # Update cluster workload count (once per workload group)
        target_cluster.workload_count += 1
        
        return results
    
    def _create_namespaces(self, namespace: str) -> None:
        """Create namespace on both clusters."""
        logger.debug(f"Creating namespace '{namespace}' on both clusters...")
        OpenShiftClient.create_project(self.config.cluster1, namespace)
        OpenShiftClient.create_project(self.config.cluster2, namespace)
    
    def _deploy_to_cluster(self, cluster: ClusterConfig, namespace: str) -> None:
        """Deploy workload to the specified cluster using kustomize."""
        logger.debug(f"Deploying workload to {cluster.name} in namespace {namespace}...")
        OpenShiftClient.apply_kustomize(cluster, self.kustomize_path, namespace)
    
    def _setup_vm_resources(self, namespace: str) -> None:
        """Setup VM resources if workload is VM type."""
        use_default_repo = self.config.repo == DEFAULT_GIT_REPO or not self.config.git_token
        VMResourceManager.setup_vm_resources(
            self.config.cluster1,
            self.config.cluster2,
            namespace,
            use_default_repo
        )
    
    def _create_dr_resources_for_group(
        self,
        namespaces: List[str],
        counter: int,
        target_cluster: ClusterConfig,
        policy_name: str
    ) -> List[Dict]:
        """
        Create DR protection resources for a GROUP of namespaces.
        Creates ONE DRPC that protects ALL namespaces in the group.
        """
        logger.debug(f"Creating DR resources for {len(namespaces)} namespace(s): {namespaces}")
        
        yaml_docs = []
        
        # Generate group name for DRPC
        if self.config.multi_ns_workload > 1:
            # For multi-ns, use the base name without the -N suffix
            drpc_name = WorkloadManager.generate_name(
                self.config.workload_type,
                self.config.workload,
                self.config.workload_pvc_type,
                counter,
                self.config.ns_dr_prefix,
                self.config.cg,
                self.config.recipe
            )
            # Add multi suffix to indicate it's a group
            drpc_name = f"{drpc_name}-multi"
        else:
            drpc_name = namespaces[0]
        
        # Load templates
        placement_template = YAMLHelper.load(WORKLOAD_DATA_DIR / "placement.yaml")[0]
        drpc_template = YAMLHelper.load(WORKLOAD_DATA_DIR / "drpc.yaml")[0]
        
        # Update Placement
        placement_template["metadata"]["name"] = f"{drpc_name}-placs-1"
        placement_template["metadata"]["namespace"] = "openshift-dr-ops"
        
        # Update DRPC
        drpc_template["metadata"]["name"] = drpc_name
        drpc_template["spec"]["drPolicyRef"]["name"] = policy_name
        drpc_template["spec"]["placementRef"]["name"] = f"{drpc_name}-placs-1"
        drpc_template["spec"]["preferredCluster"] = target_cluster.name
        
        # CRITICAL: Set ALL namespaces in protectedNamespaces
        drpc_template["spec"]["protectedNamespaces"] = namespaces
        
        logger.info(f"  DRPC '{drpc_name}' will protect namespaces: {namespaces}")
        
        # Configure selectors based on recipe or direct protection
        if not self.config.recipe:
            self._configure_direct_protection(drpc_template)
        else:
            # For recipe with multi-namespace, create recipes for all namespaces
            self._configure_recipe_protection_multi(drpc_template, namespaces, drpc_name)
        
        # Add CG annotation if enabled
        if self.config.cg:
            drpc_template["metadata"].setdefault("annotations", {}).setdefault(
                "drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true"
            )
        
        yaml_docs.extend([placement_template, drpc_template])
        
        # Create recipes if needed (one per namespace)
        if self.config.recipe:
            for namespace in namespaces:
                recipe_doc = self._create_recipe(namespace)
                yaml_docs.append(recipe_doc)
        
        return yaml_docs
    
    def _create_dr_resources(
        self,
        workload_name: str,
        target_cluster: ClusterConfig,
        policy_name: str
    ) -> List[Dict]:
        """
        Create DR protection resources for a single namespace.
        (Kept for backward compatibility with single namespace deployments)
        """
        return self._create_dr_resources_for_group(
            [workload_name],
            0,  # counter not used for single namespace
            target_cluster,
            policy_name
        )
    
    def _configure_direct_protection(self, drpc: Dict) -> None:
        """Configure DRPC for direct PVC/Pod protection."""
        pvc_sel = drpc["spec"]["pvcSelector"]["matchExpressions"][0]
        pvc_sel["key"] = self.workload_details.pvc_selector_key
        pvc_sel["values"] = [self.workload_details.pvc_selector_value]
        
        kube_sel = drpc["spec"]["kubeObjectProtection"]["kubeObjectSelector"]["matchExpressions"][0]
        kube_sel["key"] = self.workload_details.pod_selector_key
        kube_sel["values"] = [self.workload_details.pod_selector_value]
    
    def _configure_recipe_protection(self, drpc: Dict, workload_name: str) -> None:
        """Configure DRPC for recipe-based protection."""
        drpc["spec"]["pvcSelector"] = {}
        kube_prot = drpc["spec"]["kubeObjectProtection"]
        kube_prot.setdefault("recipeRef", {})["name"] = workload_name
        kube_prot["recipeRef"]["namespace"] = workload_name
        
        if "kubeObjectSelector" in kube_prot:
            del kube_prot["kubeObjectSelector"]
    
    def _configure_recipe_protection_multi(self, drpc: Dict, namespaces: List[str], drpc_name: str) -> None:
        """
        Configure DRPC for recipe-based protection with multiple namespaces.
        Note: Recipe references will point to individual namespace recipes.
        """
        drpc["spec"]["pvcSelector"] = {}
        kube_prot = drpc["spec"]["kubeObjectProtection"]
        
        # For multi-namespace, we use the first namespace's recipe as reference
        # Each namespace will have its own recipe created
        kube_prot.setdefault("recipeRef", {})["name"] = namespaces[0]
        kube_prot["recipeRef"]["namespace"] = namespaces[0]
        
        if "kubeObjectSelector" in kube_prot:
            del kube_prot["kubeObjectSelector"]
        
        logger.debug(f"  Recipe protection configured for {len(namespaces)} namespaces")
    
    def _create_recipe(self, workload_name: str) -> Dict:
        """Create recipe resource for workload protection."""
        recipe_template = YAMLHelper.load(WORKLOAD_DATA_DIR / "recipe.yaml")[0]
        
        recipe_template["metadata"]["name"] = workload_name
        recipe_template["spec"]["appType"] = self.workload_details.workload
        
        group = recipe_template["spec"]["groups"][0]
        group["backupRef"] = workload_name
        group["includedNamespaces"] = [workload_name]
        group["name"] = workload_name
        
        group_sel = group["labelSelector"]["matchExpressions"][0]
        group_sel["key"] = self.workload_details.pod_selector_key
        group_sel["values"] = [self.workload_details.pod_selector_value]
        
        recipe_template["spec"]["workflows"][0]["sequence"][1]["group"] = workload_name
        recipe_template["spec"]["workflows"][1]["sequence"][0]["group"] = workload_name
        recipe_template["spec"]["hooks"][0]["namespace"] = workload_name
        recipe_template["spec"]["hooks"][0]["nameSelector"] = f"{self.workload_details.workload}-*"
        
        vol_spec = recipe_template["spec"]["volumes"]
        vol_spec["includedNamespaces"] = [workload_name]
        vol_sel = vol_spec["labelSelector"]["matchExpressions"][0]
        vol_sel["key"] = self.workload_details.pvc_selector_key
        vol_sel["values"] = [self.workload_details.pvc_selector_value]
        
        # Create recipe on both clusters
        temp_recipe_path = OUTPUT_DATA_DIR / f"temp-recipe-{workload_name}.yaml"
        YAMLHelper.write([recipe_template], temp_recipe_path)
        
        OpenShiftClient.create_resource(
            self.config.cluster1, temp_recipe_path, f"recipe for {workload_name}"
        )
        OpenShiftClient.create_resource(
            self.config.cluster2, temp_recipe_path, f"recipe for {workload_name}"
        )
        
        temp_recipe_path.unlink()
        
        return recipe_template


# --- Deployment Statistics ---

@dataclass
class DeploymentStatistics:
    """Statistics for deployment operations."""
    total_requested: int = 0
    total_namespaces: int = 0  # Total namespaces created
    successful: int = 0
    failed: int = 0
    cluster1_count: int = 0
    cluster2_count: int = 0
    results: List[DeploymentResult] = field(default_factory=list)
    
    def add_result(self, result: DeploymentResult, cluster1_name: str) -> None:
        """Add a deployment result and update statistics."""
        self.results.append(result)
        self.total_namespaces += 1
        
        if result.success:
            self.successful += 1
            if result.cluster_name == cluster1_name:
                self.cluster1_count += 1
            else:
                self.cluster2_count += 1
        else:
            self.failed += 1
    
    def print_summary(self, cluster1_name: str, cluster2_name: str, multi_ns_workload: int) -> None:
        """Print deployment summary."""
        logger.info("=" * 70)
        logger.info("DEPLOYMENT SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Workload groups requested: {self.total_requested}")
        if multi_ns_workload > 1:
            logger.info(f"Namespaces per group:      {multi_ns_workload}")
        logger.info(f"Total namespaces created:  {self.total_namespaces}")
        logger.info(f"Successful deployments:    {self.successful} ✅")
        logger.info(f"Failed deployments:        {self.failed} ❌")
        logger.info(f"")
        logger.info(f"Distribution:")
        logger.info(f"  {cluster1_name}: {self.cluster1_count} namespaces")
        logger.info(f"  {cluster2_name}: {self.cluster2_count} namespaces")
        logger.info("=" * 70)
        
        if self.failed > 0:
            logger.info("\nFailed deployments:")
            for result in self.results:
                if not result.success:
                    logger.error(f"  - {result.workload_name}: {result.error_message}")


# --- Main Deployment Orchestrator ---

class WorkloadDeployer:
    """Orchestrates workload deployment."""
    
    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.workload_details = WorkloadManager.get_details(
            config.workload_pvc_type,
            config.workload,
            config.vm_type
        )
        self.statistics = DeploymentStatistics(total_requested=config.workload_count)
    
    def deploy_all(self) -> None:
        """Deploy all workloads."""
        logger.info(f"🚀 Starting deployment of {self.config.workload_count} workload group(s)...")
        logger.info(f"Workload type: {self.config.workload_type}")
        logger.info(f"PVC type: {self.config.workload_pvc_type}")
        logger.info(f"Workload: {self.config.workload}")
        
        if self.config.multi_ns_workload > 1:
            logger.info(f"Multi-namespace mode: {self.config.multi_ns_workload} namespaces per workload group")
            logger.info(f"Total namespaces to create: {self.config.workload_count * self.config.multi_ns_workload}")
        
        # Get policy names
        policy_names = self._get_policy_names()
        
        # Get existing workload count
        current_count = OpenShiftClient.get_existing_workload_count(
            self.config.workload_type,
            self.config.workload_pvc_type,
            self.config.workload,
            self.config.cg,
            self.config.cluster1.kubeconfig
        )
        
        # Deploy based on workload type
        if self.config.workload_type == "dist":
            self._deploy_distributed_workloads(current_count, policy_names)
        elif self.config.workload_type == "appset":
            self._deploy_applicationset_workloads(current_count, policy_names)
        elif self.config.workload_type == "sub":
            self._deploy_subscription_workloads(current_count, policy_names)
        else:
            logger.error(f"❌ Unsupported workload type: {self.config.workload_type}")
            sys.exit(1)
        
        # Print summary
        self.statistics.print_summary(
            self.config.cluster1.name,
            self.config.cluster2.name,
            self.config.multi_ns_workload
        )
        
        logger.info("✅ Script execution finished")
    
    def _deploy_distributed_workloads(
        self,
        current_count: int,
        policy_names: List[str]
    ) -> None:
        """Deploy distributed workloads."""
        logger.info(f"\n📦 Deploying DISTRIBUTED workloads...")
        
        # Setup Git repo
        kustomize_path = self._setup_git_repo()
        
        # Create cluster selector
        strategy_map = {
            'round_robin': ClusterSelectionStrategy.ROUND_ROBIN,
            'random': ClusterSelectionStrategy.RANDOM,
            'least_loaded': ClusterSelectionStrategy.LEAST_LOADED
        }
        strategy = strategy_map.get(
            getattr(self.config, 'cluster_strategy', 'round_robin'),
            ClusterSelectionStrategy.ROUND_ROBIN
        )
        
        cluster_selector = ClusterSelector(
            self.config.cluster1,
            self.config.cluster2,
            strategy,
            self.config.deploy_on
        )
        
        # Create deployer
        deployer = DistributedWorkloadDeployer(
            self.config,
            self.workload_details,
            cluster_selector,
            kustomize_path
        )
        
        # Deploy each workload group
        all_output_yaml = []
        for i in range(1, self.config.workload_count + 1):
            dynamic_i = current_count + i
            policy_name = policy_names[(i - 1) % len(policy_names)]
            
            # Generate base workload name (for single namespace mode)
            base_workload_name = WorkloadManager.generate_name(
                self.config.workload_type,
                self.config.workload,
                self.config.workload_pvc_type,
                dynamic_i,
                self.config.ns_dr_prefix,
                self.config.cg,
                self.config.recipe
            )
            
            if self.config.multi_ns_workload > 1:
                logger.info(f"\n{'='*70}")
                logger.info(f"[{i}/{self.config.workload_count}] Deploying workload group {dynamic_i} "
                           f"with {self.config.multi_ns_workload} namespaces")
                logger.info(f"{'='*70}")
            else:
                logger.info(f"\n--- [{i}/{self.config.workload_count}] Deploying: {base_workload_name} ---")
            
            # Deploy returns list of results (one per namespace)
            results = deployer.deploy(base_workload_name, dynamic_i, policy_name)
            
            # Add all results to statistics
            for result in results:
                self.statistics.add_result(result, self.config.cluster1.name)
                if result.yaml_docs:
                    all_output_yaml.extend(result.yaml_docs)
        
        # Write combined output
        self._write_combined_output(all_output_yaml)
    
    def _deploy_applicationset_workloads(
        self,
        current_count: int,
        policy_names: List[str]
    ) -> None:
        """Deploy ApplicationSet workloads."""
        logger.info(f"\n📦 Deploying APPLICATIONSET workloads...")
        
        # Load ApplicationSet template
        template_path = WORKLOAD_DATA_DIR / "sample_appset_rbd.yaml"
        if not template_path.exists():
            logger.error(f"❌ Template not found: {template_path}")
            sys.exit(1)
        
        template_data = YAMLHelper.load(template_path)
        
        # Get repository details
        git_repo = self.config.repo or DEFAULT_GIT_REPO
        git_branch = self.config.repo_branch if self.config.repo else DEFAULT_GIT_BRANCH
        
        all_output_yaml = []
        for i in range(1, self.config.workload_count + 1):
            dynamic_i = current_count + i
            policy_name = policy_names[(i - 1) % len(policy_names)]
            
            workload_name = WorkloadManager.generate_name(
                self.config.workload_type,
                self.config.workload,
                self.config.workload_pvc_type,
                dynamic_i,
                self.config.ns_dr_prefix,
                self.config.cg,
                self.config.recipe
            )
            
            logger.info(f"\n--- [{i}/{self.config.workload_count}] Creating: {workload_name} ---")
            
            try:
                # Update ApplicationSet YAML
                updated_yaml, workload_cluster = self._update_appset_yaml(
                    template_data,
                    workload_name,
                    policy_name,
                    git_repo,
                    git_branch
                )
                all_output_yaml.extend(updated_yaml)
                
                logger.info(f"✅ ApplicationSet '{workload_name}' YAML created for {workload_cluster}")
                
                # Track deployment in statistics
                result = DeploymentResult(
                    success=True,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name=workload_cluster
                )
                self.statistics.add_result(result, self.config.cluster1.name)
                
            except Exception as e:
                logger.error(f"❌ Failed to create ApplicationSet {workload_name}: {e}")
                # Track failure
                result = DeploymentResult(
                    success=False,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name="unknown",
                    error_message=str(e)
                )
                self.statistics.add_result(result, self.config.cluster1.name)
                continue
        
        # Write combined output
        self._write_combined_output(all_output_yaml)
    
    def _deploy_subscription_workloads(
        self,
        current_count: int,
        policy_names: List[str]
    ) -> None:
        """Deploy Subscription workloads."""
        logger.info(f"\n📦 Deploying SUBSCRIPTION workloads...")
        
        # Load Subscription template
        template_path = WORKLOAD_DATA_DIR / "sample_sub_rbd.yaml"
        if not template_path.exists():
            logger.error(f"❌ Template not found: {template_path}")
            sys.exit(1)
        
        template_data = YAMLHelper.load(template_path)
        
        # Get repository details
        git_repo = self.config.repo or DEFAULT_GIT_REPO
        git_branch = self.config.repo_branch if self.config.repo else DEFAULT_GIT_BRANCH
        
        all_output_yaml = []
        for i in range(1, self.config.workload_count + 1):
            dynamic_i = current_count + i
            policy_name = policy_names[(i - 1) % len(policy_names)]
            
            workload_name = WorkloadManager.generate_name(
                self.config.workload_type,
                self.config.workload,
                self.config.workload_pvc_type,
                dynamic_i,
                self.config.ns_dr_prefix,
                self.config.cg,
                self.config.recipe
            )
            
            logger.info(f"\n--- [{i}/{self.config.workload_count}] Creating: {workload_name} ---")
            
            try:
                # Update Subscription YAML
                updated_yaml, workload_cluster = self._update_sub_yaml(
                    template_data,
                    workload_name,
                    policy_name,
                    git_repo,
                    git_branch
                )
                all_output_yaml.extend(updated_yaml)
                
                logger.info(f"✅ Subscription '{workload_name}' YAML created for {workload_cluster}")
                
                # Track deployment in statistics
                result = DeploymentResult(
                    success=True,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name=workload_cluster
                )
                self.statistics.add_result(result, self.config.cluster1.name)
                
            except Exception as e:
                logger.error(f"❌ Failed to create Subscription {workload_name}: {e}")
                # Track failure
                result = DeploymentResult(
                    success=False,
                    workload_name=workload_name,
                    namespace=workload_name,
                    cluster_name="unknown",
                    error_message=str(e)
                )
                self.statistics.add_result(result, self.config.cluster1.name)
                continue
        
        # Write combined output
        self._write_combined_output(all_output_yaml)
    
    def _setup_git_repo(self) -> Path:
        """Setup Git repository and return kustomize path."""
        git_repo = self.config.repo or DEFAULT_GIT_REPO
        git_branch = self.config.repo_branch if self.config.repo else DEFAULT_GIT_BRANCH
        clone_path = SCRIPT_DIR / CLONE_DIR_NAME
        
        # Add token if provided
        if self.config.git_token:
            git_repo = git_repo.replace("https://", f"https://{self.config.git_token}@")
        
        # Clone repository
        GitHelper.clone_and_checkout(git_repo, clone_path, git_branch)
        
        # Build kustomize path
        kustomize_path = clone_path / self.workload_details.path
        
        if not kustomize_path.exists():
            logger.error(f"❌ Workload path not found: {kustomize_path}")
            sys.exit(1)
        
        logger.info(f"✅ Kustomize path ready: {kustomize_path}")
        return kustomize_path
    
    def _get_policy_names(self) -> List[str]:
        """Get list of DR policy names."""
        if self.config.drpolicy_name:
            OpenShiftClient.validate_drpolicy(self.config.drpolicy_name)
            return [self.config.drpolicy_name]
        
        try:
            result = OpenShiftClient.run_command(["get", "drpolicy", "--no-headers"])
            policy_names = [
                line.split()[0]
                for line in result.stdout.strip().split('\n')
                if line.strip()
            ]
            
            if not policy_names:
                logger.error("❌ No DRPolicies found")
                sys.exit(1)
            
            logger.info(f"Found DR policies: {', '.join(policy_names)}")
            return policy_names
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to list DRPolicies: {e.stderr}")
            sys.exit(1)
    
    
    def _update_appset_yaml(
        self,
        template_data: List[Dict],
        workload_name: str,
        policy_name: str,
        git_repo: str,
        git_branch: str
    ) -> Tuple[List[Dict], str]:
        """Update ApplicationSet YAML with workload-specific values.
        
        Returns:
            Tuple of (updated_yaml_list, workload_cluster)
        """
        updated_data = copy.deepcopy(template_data)
        
        # Determine deployment cluster
        workload_cluster = self.config.deploy_on or random.choice([
            self.config.cluster1.name,
            self.config.cluster2.name
        ])
        
        for item in updated_data:
            if item["kind"] == "ApplicationSet":
                item["metadata"]["name"] = workload_name
                item["spec"]["generators"][0]["clusterDecisionResource"]["labelSelector"]["matchLabels"]["cluster.open-cluster-management.io/placement"] = f"{workload_name}-placs"
                item["spec"]["template"]["metadata"]["name"] = f"{workload_name}-{{{{name}}}}"
                item["spec"]["template"]["spec"]["sources"][0]["path"] = self.workload_details.path
                item["spec"]["template"]["spec"]["sources"][0]["repoURL"] = git_repo
                item["spec"]["template"]["spec"]["sources"][0]["targetRevision"] = git_branch
                item["spec"]["template"]["spec"]["destination"]["namespace"] = workload_name
                
            elif item["kind"] == "Placement":
                item["metadata"]["name"] = f"{workload_name}-placs"
                item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
                item["spec"]["clusterSets"][0] = self.config.clusterset
                
                if self.config.protect_workload == "yes":
                    item["metadata"].setdefault("annotations", {}).setdefault(
                        "cluster.open-cluster-management.io/experimental-scheduling-disable", "true"
                    )
                    
            elif item["kind"] == "DRPlacementControl" and self.config.protect_workload == "yes":
                item["metadata"]["name"] = f"{workload_name}-placs-drpc"
                item["spec"]["drPolicyRef"]["name"] = policy_name
                item["spec"]["placementRef"]["name"] = f"{workload_name}-placs"
                item["spec"]["preferredCluster"] = workload_cluster
                
                pvc_sel = item["spec"]["pvcSelector"]["matchExpressions"][0]
                pvc_sel["key"] = self.workload_details.pvc_selector_key
                pvc_sel["values"] = [self.workload_details.pvc_selector_value]
                
                if self.config.cg:
                    item["metadata"].setdefault("annotations", {}).setdefault(
                        "drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true"
                    )
        
        # Filter out DRPC if protection is disabled
        if self.config.protect_workload != "yes":
            updated_data = [item for item in updated_data if item["kind"] != "DRPlacementControl"]
        
        return updated_data, workload_cluster
    
    def _update_sub_yaml(
        self,
        template_data: List[Dict],
        workload_name: str,
        policy_name: str,
        git_repo: str,
        git_branch: str
    ) -> Tuple[List[Dict], str]:
        """Update Subscription YAML with workload-specific values.
        
        Returns:
            Tuple of (updated_yaml_list, workload_cluster)
        """
        updated_data = copy.deepcopy(template_data)
        
        channel = f"channel-{workload_name}"
        
        # Determine deployment cluster
        workload_cluster = self.config.deploy_on or random.choice([
            self.config.cluster1.name,
            self.config.cluster2.name
        ])
        
        for item in updated_data:
            if item["kind"] == "Namespace":
                # First namespace is for workload, second for channel
                if item["metadata"]["name"] in ["sub-rbd-1", "busybox-sub"]:
                    item["metadata"]["name"] = workload_name
                else:
                    item["metadata"]["name"] = channel
                    
            elif item["kind"] == "Application":
                item["metadata"]["name"] = workload_name
                item["metadata"]["namespace"] = workload_name
                item["spec"]["selector"]["matchExpressions"][0]["values"][0] = workload_name
                
            elif item["kind"] == "Channel":
                item["metadata"]["name"] = channel
                item["metadata"]["namespace"] = channel
                item["spec"]["pathname"] = git_repo
                
            elif item["kind"] == "Subscription":
                item["metadata"]["name"] = f"{workload_name}-sub"
                item["metadata"]["namespace"] = workload_name
                item["metadata"]["annotations"]["apps.open-cluster-management.io/git-branch"] = git_branch
                item["metadata"]["annotations"]["apps.open-cluster-management.io/git-path"] = self.workload_details.path
                item["metadata"]["labels"]["app"] = workload_name
                item["spec"]["channel"] = f"{channel}/{channel}"
                item["spec"]["placement"]["placementRef"]["name"] = f"{workload_name}-placs"
                
            elif item["kind"] == "Placement":
                item["metadata"]["labels"]["app"] = workload_name
                item["metadata"]["name"] = f"{workload_name}-placs"
                item["metadata"]["namespace"] = workload_name
                item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
                item["spec"]["clusterSets"][0] = self.config.clusterset
                
                if self.config.protect_workload == "yes":
                    item["metadata"].setdefault("annotations", {}).setdefault(
                        "cluster.open-cluster-management.io/experimental-scheduling-disable", "true"
                    )
                    
            elif item["kind"] == "ManagedClusterSetBinding":
                item["metadata"]["namespace"] = workload_name
                item["metadata"]["name"] = self.config.clusterset
                item["spec"]["clusterSet"] = self.config.clusterset
                
            elif item["kind"] == "DRPlacementControl" and self.config.protect_workload == "yes":
                item["metadata"]["name"] = f"{workload_name}-placs-drpc"
                item["metadata"]["namespace"] = workload_name
                item["spec"]["drPolicyRef"]["name"] = policy_name
                item["spec"]["placementRef"]["name"] = f"{workload_name}-placs"
                item["spec"]["placementRef"]["namespace"] = workload_name
                item["spec"]["preferredCluster"] = workload_cluster
                
                pvc_sel = item["spec"]["pvcSelector"]["matchExpressions"][0]
                pvc_sel["key"] = self.workload_details.pvc_selector_key
                pvc_sel["values"] = [self.workload_details.pvc_selector_value]
                
                if self.config.cg:
                    item["metadata"].setdefault("annotations", {}).setdefault(
                        "drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true"
                    )
        
        # Filter out DRPC if protection is disabled
        if self.config.protect_workload != "yes":
            updated_data = [item for item in updated_data if item["kind"] != "DRPlacementControl"]
        
        return updated_data, workload_cluster
    
    def _write_combined_output(self, yaml_docs: List[Dict]) -> None:
        """Write all YAML documents to a single output file."""
        if not yaml_docs:
            logger.warning("⚠ No YAML documents generated")
            return
        
        ns_prefix = f"{self.config.ns_dr_prefix}_" if self.config.ns_dr_prefix else ""
        multi_suffix = f"_multi{self.config.multi_ns_workload}" if self.config.multi_ns_workload > 1 else ""
        file_name = (
            f"output_{ns_prefix}{self.config.workload_type}_"
            f"{self.config.workload_pvc_type}_{self.config.workload}{multi_suffix}_combined.yaml"
        )
        output_file = self.config.output_dir_path / file_name
        
        logger.info(f"\n💾 Writing combined YAML to: {output_file}")
        YAMLHelper.write(yaml_docs, output_file)


# --- Entry Point ---

def main():
    """Main entry point."""
    # Parse arguments
    args = ConfigLoader.parse_args()
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    # Validate configuration
    ConfigValidator.validate(args)
    
    # Determine cluster selection strategy
    strategy_map = {
        'round_robin': ClusterSelectionStrategy.ROUND_ROBIN,
        'random': ClusterSelectionStrategy.RANDOM,
        'least_loaded': ClusterSelectionStrategy.LEAST_LOADED
    }
    selection_strategy = strategy_map.get(
        getattr(args, 'cluster_strategy', 'round_robin'),
        ClusterSelectionStrategy.ROUND_ROBIN
    )
    
    # Create deployment config
    config = DeploymentConfig(
        workload_pvc_type=args.workload_pvc_type,
        workload_type=args.workload_type,
        workload_count=args.workload_count,
        deploy_on=args.deploy_on,
        output_dir_path=args.output_dir_path,
        protect_workload=args.protect_workload,
        drpolicy_name=args.drpolicy_name,
        cg=args.cg,
        workload=args.workload,
        ns_dr_prefix=args.ns_dr_prefix,
        recipe=args.recipe,
        repo=args.repo,
        repo_branch=args.repo_branch,
        git_token=args.git_token,
        clusterset=args.clusterset or OpenShiftClient.get_clusterset_name(args.c1_name),
        cluster1=ClusterConfig(name=args.c1_name, kubeconfig=args.c1_kubeconfig),
        cluster2=ClusterConfig(name=args.c2_name, kubeconfig=args.c2_kubeconfig),
        selection_strategy=selection_strategy,
        multi_ns_workload=args.multi_ns_workload,
        vm_type=args.vm_type
    )
    
    # Deploy workloads
    deployer = WorkloadDeployer(config)
    deployer.deploy_all()


if __name__ == "__main__":
    main()