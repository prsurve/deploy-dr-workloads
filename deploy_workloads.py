import argparse
import yaml
import random
from pathlib import Path
import subprocess
import sys
import os
import logging
import shutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('-clusterset', type=str, help='Cluster set name')
    parser.add_argument('-c1_name', type=str, help='Cluster name')
    parser.add_argument('-c1_kubeconfig', type=str, help='Cluster Kubeconfig')
    parser.add_argument('-c2_name', type=str, help='Cluster set name')
    parser.add_argument('-c2_kubeconfig', type=str, help='Cluster set name')
    parser.add_argument('-workload_pvc_type', type=str, required=True, choices=['rbd', 'cephfs', 'mix'], help='Workload PVC type')
    parser.add_argument('-workload_type', type=str, required=True, choices=['appset', 'sub', 'dist'], help='Workload type')
    parser.add_argument('-workload_count', type=int, required=True, help='Number of workloads to deploy')
    parser.add_argument('-deploy_on', type=str, default=None, help='Deploy workload on specific cluster')
    parser.add_argument('-output_dir', type=str, required=True, help='Directory to write output YAML files')
    parser.add_argument('-protect_workload', type=str, required=True, choices=['yes', 'no'], help='Protect the workload')
    parser.add_argument('-drpolicy_name', type=str, default=None, help='Disaster Recovery Policy name')
    parser.add_argument('-cg', type=bool, default=False, help='Consistency Group')
    parser.add_argument('-workload', type=str, default="busybox", choices=['busybox', 'vm', 'mysql'], help='Workload That you want to deploy')
    parser.add_argument('-ns_dr_prefix', type=str, default=False, help='Name to add as prefix')
    parser.add_argument('-recipe', type=bool, default=False, help='Protect discovered based workload using recipe')
    parser.add_argument('-repo', type=str, default=None, help='Repo to use for dist worklaods')
    parser.add_argument('-repo_branch', type=str, default="less_workload", help='Branch to use for repo ')


    return parser.parse_args()


def get_workload_path(pvc_type):
    """Return workload path based on PVC type."""
    return f"rdr/busybox/{pvc_type}/workloads/app-busybox-1"

def get_workload_path(pvc_type, workload):
    """Return workload path based on PVC type."""
    if workload == "busybox":
        if pvc_type == "mix-workload":
            path=f"rdr/busybox/{pvc_type}/workloads/app-busybox-1"
            workload_pod_selector_key="workloadpattern"
            workload_pod_selector_value="simple_io"
            workload_pvc_selector_key="appname"
            workload_pvc_selector_value="busybox_app_mix"
        else:
            path=f"rdr/busybox/{pvc_type}/workloads/app-busybox-1"
            workload_pod_selector_key="workloadpattern"
            workload_pod_selector_value="simple_io"
            workload_pvc_selector_key="workloadpattern"
            workload_pvc_selector_value="simple_io_pvc"


    elif workload == "vm":
        path="rdr/cnv-workload/vm-resources/vm-workload-1"
        workload_pod_selector_key="appname"
        workload_pod_selector_value="kubevirt"
        workload_pvc_selector_key="appname"
        workload_pvc_selector_value="kubevirt"
    else:
        path=f"rdr/mysql/{pvc_type}/workloads/app-mysql-1"
        workload_pod_selector_key="appname"
        workload_pod_selector_value="mysql_app_1"
        workload_pvc_selector_key="workloadpattern"
        workload_pvc_selector_value="mysql_io_pvc"

    return_dict = {"workload_path": path, "workload": workload, "workload_pod_selector_key": workload_pod_selector_key, "workload_pod_selector_value": workload_pod_selector_value, 
            "workload_pvc_selector_key": workload_pvc_selector_key, "workload_pvc_selector_value": workload_pvc_selector_value}
    return return_dict

def load_yaml_file(filepath):
    """Load and return YAML content from the given file."""
    with open(filepath, 'r') as file:
        return list(yaml.safe_load_all(file))
def create_project(kubeconfig, cluster_name, project_name):
    """Create a project if it does not already exist."""
    try:
        cmd = ["oc", "--kubeconfig", kubeconfig, "new-project", project_name]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"✅ Project '{project_name}' created on {cluster_name}.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "already exists" in stderr:
            logger.info(f"⚠ Project '{project_name}' already exists on {cluster_name}, skipping creation.")
        else:
            logger.info(f"❌ Failed to create project '{project_name}' on {cluster_name}:\n{stderr}")


def create_resource(kubeconfig, cluster_name, yaml_file, resource_label):
    """Create a resource from a YAML file if it does not already exist."""
    try:
        cmd = ["oc", "--kubeconfig", kubeconfig, "create", "-f", yaml_file]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"✅ Created {resource_label} on {cluster_name}.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "AlreadyExists" in stderr or "already exists" in stderr:
            logger.info(f"⚠ {resource_label} already exists on {cluster_name}, skipping creation.")
        else:
            logger.info(f"❌ Failed to create {resource_label} on {cluster_name}:\n{stderr}")



def update_appset_yaml(appset_data, pvc_type, cluster_set, deploy_on, c1, c2, counter, workload_path, protect_workload, drpolicy_name, cg, workload_dict, c1_dict, c2_dict, ns_dr_prefix, repo_branch):
    """Update ApplicationSet YAML based on provided parameters."""
    name_suffix=""
    ns_dr_prf=""
    if cg:
        name_suffix="-cg"
    workload = workload_dict.get("workload")
    
    if ns_dr_prefix:
        ns_dr_prf = ns_dr_prefix+"-"
    workload_name = f"{ns_dr_prf}app-{workload}-{pvc_type}-{counter}{name_suffix}"
    if cg:
        if workload == "busybox":
            workload="bb"
        elif workload == "busybox":
            workload="vm"
        elif workload == "mysql":
            workload="my"
        if not ns_dr_prefix:
            ns_dr_prf = ns_dr_prefix+"-"
        workload_name = f"{ns_dr_prf}ap-{workload}-{pvc_type}-{counter}{name_suffix}"
    workload_cluster = deploy_on or random.choice([c1, c2])
    for item in appset_data:
        if item["kind"] == "ApplicationSet":
            item["metadata"]["name"] = workload_name
            item["spec"]["generators"][0]["clusterDecisionResource"]["labelSelector"]["matchLabels"]["cluster.open-cluster-management.io/placement"] = f"{ workload_name}-placs"
            item["spec"]["template"]["metadata"]["name"] = f"{workload_name}-{{{{name}}}}"
            item["spec"]["template"]["spec"]["sources"][0]["path"] = workload_path
            item["spec"]["template"]["spec"]["sources"][0]["targetRevision"] = repo_branch

            item["spec"]["template"]["spec"]["destination"]["namespace"] = workload_name
        elif item["kind"] == "Placement":
            item["metadata"]["name"] = f"{workload_name}-placs"
            item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
            item["spec"]["clusterSets"][0] = cluster_set
            if protect_workload == "yes":
                item["metadata"].setdefault("annotations", {}).setdefault("cluster.open-cluster-management.io/experimental-scheduling-disable", "true")
        elif item["kind"] == "DRPlacementControl" and protect_workload == "yes":
            item["metadata"]["name"] = f"{workload_name}-placs-drpc"
            item["spec"]["drPolicyRef"]["name"] = drpolicy_name
            item["spec"]["placementRef"]["name"] = f"{workload_name}-placs"
            item["spec"]["preferredCluster"] = workload_cluster
            item["spec"]["pvcSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pvc_selector_key")
            item["spec"]["pvcSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pvc_selector_value")
            if cg:
                item["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")
    if workload_dict.get('workload') == "vm":
        create_project(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),workload_name)
        create_project(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),workload_name)
        yaml_file = str(Path(f"workload_data/vm-secret.yaml"))
        vm_secret_yaml_dict = load_yaml_file(yaml_file)[0]
        vm_secret_yaml_dict["metadata"]["namespace"]=workload_name
        write_output_yaml([vm_secret_yaml_dict], "workload_data/vm-secret.yaml")
        create_resource(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),"workload_data/vm-secret.yaml", "vm-secret")
        create_resource(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),"workload_data/vm-secret.yaml", "vm-secret")
    return appset_data


def get_managed_clusters():
    """Get list of managed clusters."""
    result = subprocess.run(
        "oc get managedcluster | grep -v 'local-cluster' | grep -v 'Unknown' | grep -v 'NAME' | awk '{print $1}'",
        shell=True, capture_output=True, text=True, check=True
    )
    return [c for c in result.stdout.strip().split('\n') if c]


def get_clusterset_name(cluster_name):
    """Get clusterset name for a given cluster."""
    result = subprocess.run(
        ["oc", "get", "managedcluster", cluster_name, "-o", "yaml"],
        capture_output=True, text=True, check=True
    )
    data = yaml.safe_load(result.stdout)
    return data.get("metadata", {}).get("labels", {}).get("cluster.open-cluster-management.io/clusterset")


def update_sub_yaml(sub_data, pvc_type, cluster_set, deploy_on, c1, c2, counter, workload_path, protect_workload, drpolicy_name, cg, workload_dict, c1_dict, c2_dict,ns_dr_prefix, repo_branch):
    """Update Subscription YAML based on provided parameters."""
    name_suffix=""
    ns_dr_prf=""
    if cg:
        name_suffix="-cg"
    if ns_dr_prefix:
        ns_dr_prf = ns_dr_prefix+"-"
    name = f"{ns_dr_prf}sub-{workload_dict.get('workload')}-{pvc_type}-{counter}{name_suffix}"
    channel = f"sub-channel-{workload_dict.get('workload')}-{pvc_type}-{counter}"
    workload_cluster = deploy_on or random.choice([c1, c2])
    for item in sub_data:
        if item["kind"] == "Namespace":
            item["metadata"]["name"] = name if item["metadata"]["name"] == "sub-rbd-1" else channel
        elif item["kind"] == "Application":
            item["metadata"]["name"] = item["metadata"]["namespace"] = name
            item["spec"]["selector"]["matchExpressions"][0]["values"][0] = name
        elif item["kind"] == "Channel":
            item["metadata"]["name"] = item["metadata"]["namespace"] = channel
        elif item["kind"] == "Subscription":
            item["metadata"]["name"] = f"{name}-subscription-{counter}"
            item["metadata"]["namespace"] = name
            item["metadata"]["annotations"]["apps.open-cluster-management.io/git-branch"] = repo_branch
            item["metadata"]["annotations"]["apps.open-cluster-management.io/git-path"] = workload_path
            item["metadata"]["labels"]["app"] = name
            item["spec"]["channel"] = f"{channel}/{channel}"
            item["spec"]["placement"]["placementRef"]["name"] = f"{name}-placs-{counter}"
        elif item["kind"] == "Placement":
            item["metadata"]["labels"]["app"] = name
            item["metadata"]["name"] = f"{name}-placs-{counter}"
            item["metadata"]["namespace"] = name
            item["spec"]["predicates"][0]["requiredClusterSelector"]["labelSelector"]["matchExpressions"][0]["values"][0] = workload_cluster
            item["spec"]["clusterSets"][0] = cluster_set
            if protect_workload == "yes":
                item["metadata"].setdefault("annotations", {}).setdefault("cluster.open-cluster-management.io/experimental-scheduling-disable", "true")
        elif item["kind"] == "ManagedClusterSetBinding":
            item["metadata"]["namespace"] = name
            item["metadata"]["name"] = cluster_set
            item["spec"]["clusterSet"] = cluster_set
        elif item["kind"] == "DRPlacementControl" and protect_workload == "yes":
            item["metadata"]["name"] = f"{name}-placs-drpc"
            item["metadata"]["namespace"] = name
            item["spec"]["drPolicyRef"]["name"] = drpolicy_name
            item["spec"]["placementRef"]["name"] = f"{name}-placs-{counter}"
            item["spec"]["placementRef"]["namespace"] = name
            item["spec"]["preferredCluster"] = workload_cluster
            item["spec"]["pvcSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pvc_selector_key")
            item["spec"]["pvcSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pvc_selector_value")
            if cg:
                item["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")
    if workload_dict.get('workload') == "vm":


        create_project(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),name)
        create_project(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),name)
        yaml_file = str(Path(f"workload_data/vm-secret.yaml"))
        vm_secret_yaml_dict = load_yaml_file(yaml_file)[0]
        vm_secret_yaml_dict["metadata"]["namespace"]=name
        write_output_yaml([vm_secret_yaml_dict], "workload_data/vm-secret.yaml")
        create_resource(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),"workload_data/vm-secret.yaml", "vm-secret")
        create_resource(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),"workload_data/vm-secret.yaml", "vm-secret")
    return sub_data


def deploy_discovered_apps(counter, workload_path, pvc_type, cluster_set, deploy_on, protect_workload, drpolicy_name, c1_dict, c2_dict, cg, workload_dict,ns_dr_prefix, recipe):
    logger.info(f"Starting to deploy discovered apps for {pvc_type} workload. Counter: {counter}")
    
    try:
        # Create the project on both clusters
        
        namespace_name_suffix=""
        ns_dr_prf=""
        recipe_prf=""
        if cg:
            namespace_name_suffix="-cg"
        if ns_dr_prefix:
            ns_dr_prf = ns_dr_prefix+"-"
        if recipe:
            recipe_prf = recipe_prf+"rp"
        namespace_name = f"{ns_dr_prf}imp-{workload_dict.get('workload')}-{pvc_type}-{recipe_prf}-{counter}{namespace_name_suffix}"
        logger.info(f"Creating project on cluster {c1_dict.get('cluster_name')} for {pvc_type}-{counter}")
        cmd = ["oc", "--kubeconfig", c1_dict.get("kubeconfig"), "new-project", namespace_name]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Project created on {c1_dict.get('cluster_name')}")

        logger.info(f"Creating project on cluster {c2_dict.get('cluster_name')} for {pvc_type}-{counter}")
        cmd = ["oc", "--kubeconfig", c2_dict.get("kubeconfig"), "new-project", namespace_name]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Project created on {c2_dict.get('cluster_name')}")

        cluster_dict = [c1_dict, c2_dict]
        if deploy_on:
            if c1_dict.get("cluster_name") == deploy_on:
                logger.info(f"Deploying workload to {c1_dict.get('cluster_name')} with workload path: {workload_path}")
                cmd = ["oc", "--kubeconfig", c1_dict.get("kubeconfig"), "create", "-k", workload_path]
            else:
                logger.info(f"Deploying workload to {c2_dict.get('cluster_name')} with workload path: {workload_path}")
                cmd = ["oc", "--kubeconfig", c2_dict.get("kubeconfig"), "create", "-k", workload_path]
        else:
            selected_cluster = random.choice(cluster_dict)
            logger.info(f"Deploying workload to randomly selected cluster: {selected_cluster.get('cluster_name')} with workload path: {workload_path}")
            cmd = ["oc", "--kubeconfig", selected_cluster.get("kubeconfig"), "create", "-k", workload_path]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if protect_workload == "yes":
            current_path = os.getcwd()

            logger.info(f"Current path: {current_path}")
            yaml_file = str(Path(f"../workload_data/placement.yaml"))
            placement_yaml_dict = load_yaml_file(yaml_file)[0]
            yaml_file = str(Path(f"../workload_data/drpc.yaml"))
            drpc_yaml_dict = load_yaml_file(yaml_file)[0]
            placement_yaml_dict["metadata"]["name"]=f"{namespace_name}-placs-1"
            placement_yaml_dict["metadata"]["namespace"]="openshift-dr-ops"

            drpc_yaml_dict["metadata"]["name"]=namespace_name
            drpc_yaml_dict["spec"]["drPolicyRef"]["name"]=drpolicy_name
            drpc_yaml_dict["spec"]["placementRef"]["name"]=f"{namespace_name}-placs-1"
            drpc_yaml_dict["spec"]["preferredCluster"] = c1_dict.get("cluster_name") if deploy_on else selected_cluster.get('cluster_name')
            drpc_yaml_dict["spec"]["protectedNamespaces"][0]=namespace_name
            
            if not recipe:
                drpc_yaml_dict["spec"]["pvcSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pvc_selector_key")
                drpc_yaml_dict["spec"]["pvcSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pvc_selector_value")
                drpc_yaml_dict["spec"]["kubeObjectProtection"]["kubeObjectSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pod_selector_key")
                drpc_yaml_dict["spec"]["kubeObjectProtection"]["kubeObjectSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pod_selector_value")
            else:
                drpc_yaml_dict["spec"]["pvcSelector"]= {}
                drpc_yaml_dict["spec"]["kubeObjectProtection"].setdefault("recipeRef", {})["name"] = namespace_name
                drpc_yaml_dict["spec"]["kubeObjectProtection"]["recipeRef"]["namespace"]=namespace_name
                del drpc_yaml_dict["spec"]["kubeObjectProtection"]["kubeObjectSelector"]
            
            if cg:
                drpc_yaml_dict["metadata"].setdefault("annotations", {}).setdefault("drplacementcontrol.ramendr.openshift.io/is-cg-enabled", "true")
            combined_dict = [placement_yaml_dict, drpc_yaml_dict]
            if recipe:
                yaml_file = str(Path(f"../workload_data/recipe.yaml"))
                recipe_yaml_dict = load_yaml_file(yaml_file)[0]

                recipe_yaml_dict["metadata"]["name"] = namespace_name
                recipe_yaml_dict["spec"]["appType"]=workload_dict.get('workload')
                recipe_yaml_dict["spec"]["groups"][0]["backupRef"]=namespace_name
                recipe_yaml_dict["spec"]["groups"][0]["includedNamespaces"] = [namespace_name]
                recipe_yaml_dict["spec"]["groups"][0]["name"] = namespace_name
                recipe_yaml_dict["spec"]["groups"][0]["labelSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pod_selector_key")
                recipe_yaml_dict["spec"]["groups"][0]["labelSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pod_selector_value")
                recipe_yaml_dict["spec"]["workflows"][0]["sequence"][1]["group"] = namespace_name
                recipe_yaml_dict["spec"]["workflows"][1]["sequence"][0]["group"] = namespace_name
                recipe_yaml_dict["spec"]["hooks"][0]["namespace"] = namespace_name
                recipe_yaml_dict["spec"]["hooks"][0]["nameSelector"] = workload_dict.get('workload')+"-*"
                recipe_yaml_dict["spec"]["volumes"]["includedNamespaces"] = [namespace_name]
                recipe_yaml_dict["spec"]["volumes"]["labelSelector"]["matchExpressions"][0]["key"]=workload_dict.get("workload_pvc_selector_key")
                recipe_yaml_dict["spec"]["volumes"]["labelSelector"]["matchExpressions"][0]["values"][0]=workload_dict.get("workload_pvc_selector_value")
                write_output_yaml([recipe_yaml_dict], "../workload_data/recipe.yaml")
                create_resource(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),"../workload_data/recipe.yaml", "recipe")
                create_resource(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),"../workload_data/recipe.yaml", "recipe")


                
        if workload_dict.get('workload') == "vm":
            
            yaml_file = str(Path(f"../workload_data/vm-secret.yaml"))
            vm_secret_yaml_dict = load_yaml_file(yaml_file)[0]
            vm_secret_yaml_dict["metadata"]["namespace"]=namespace_name
            write_output_yaml([vm_secret_yaml_dict], "../workload_data/vm-secret.yaml")
            create_resource(c1_dict.get("kubeconfig"),c1_dict.get('cluster_name'),"../workload_data/vm-secret.yaml", "vm-secret")
            create_resource(c2_dict.get("kubeconfig"),c2_dict.get('cluster_name'),"../workload_data/vm-secret.yaml", "vm-secret")
        return combined_dict
    except subprocess.CalledProcessError as e:
        logger.error(f"An error occurred during workload deployment: {e.stderr}")
        raise

    logger.info(f"Deployment of discovered apps for {pvc_type}-{counter} completed successfully.")

def change_to_script_root():
    """Change working directory to the script's root directory."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)



def clone_and_checkout(repo_url, clone_path, branch="less_workload"):
    """Clone the Git repository and checkout the master branch."""
    change_to_script_root()
    if os.path.exists(clone_path):
        logger.info(f"Directory {clone_path} already exists. Removing it.")
        shutil.rmtree(clone_path)
    
    try:
        logger.info(f"Cloning repository {repo_url} into {clone_path}")
        subprocess.run(["git", "clone", "--quiet", repo_url, clone_path, "--branch", branch], check=True)

        logger.info("Repository cloned successfully.")
        os.chdir("ocs-workloads")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clone repository: {e.stderr}")
        raise


def write_output_yaml(data, output_path):
    """Write YAML data (single or multiple docs) to a file."""
    with open(output_path, 'w') as outfile:
        # If data is iterable with multiple items → multi-doc YAML

        if isinstance(data, (list, tuple)) and len(data) > 1:
            yaml.dump_all(data, outfile, sort_keys=False, indent=2)
        else:
            # Single document — if data is list with one element, unpack it
            if isinstance(data, (list, tuple)) and len(data) == 1:
                data = data[0]
            yaml.dump(data, outfile, sort_keys=False, indent=2)
def get_first_vrc_yaml(kubeconfig):
    """Get the YAML of the first VolumeReplicationClass from a cluster."""
    vrc_list = subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "get", "vrc", "-o", "name"],
        capture_output=True, text=True, check=True
    ).stdout.splitlines()

    if not vrc_list:
        raise RuntimeError(f"No VRCs found in cluster with kubeconfig {kubeconfig}")

    vrc_name = vrc_list[0]
    vrc_yaml = subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "get", vrc_name, "-o", "yaml"],
        capture_output=True, text=True, check=True
    ).stdout

    return yaml.safe_load(vrc_yaml)


def update_vrgc_from_vrc(vrgc_dict, vrc_dict):
    """Update VRGC YAML dict based on VRC data."""
    vrgc_dict['metadata']['name'] = f"vrgc-rbd-{vrc_dict['spec']['parameters']['schedulingInterval']}"
    labels = vrgc_dict.setdefault('metadata', {}).setdefault('labels', {})
    labels['ramendr.openshift.io/storageid'] = vrc_dict['metadata']['labels']['ramendr.openshift.io/storageid']
    labels['ramendr.openshift.io/replicationid'] = vrc_dict['metadata']['labels']['ramendr.openshift.io/replicationid']

    params = vrgc_dict.setdefault('spec', {}).setdefault('parameters', {})
    params['clusterID'] = vrc_dict['spec']['parameters']['clusterID']
    params['replication.storage.openshift.io/group-replication-secret-name'] = vrc_dict['spec']['parameters']['replication.storage.openshift.io/replication-secret-name']
    params['schedulingInterval'] = vrc_dict['spec']['parameters']['schedulingInterval']


def ensure_vrgc_exists(kubeconfig, vrgc_dict, output_path):
    """Check if VRGC exists, create if missing."""
    vrgc_name = vrgc_dict['metadata']['name']
    check = subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "get", "VolumeGroupReplicationClass", vrgc_name],
        capture_output=True, text=True
    )

    if check.returncode == 0:
        logger.info(f"✅ VRGC '{vrgc_name}' already exists in cluster {kubeconfig}, skipping creation.")
        return

    # Write VRGC YAML to file
    write_output_yaml(vrgc_dict, output_path)

    subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "create", "-f", output_path],
        capture_output=True, text=True, check=True
    )
    logger.info(f"🎉 Created VGRC '{vrgc_name}' in cluster {kubeconfig}")


def create_vrgc(args):
    """Creating VolumeGroupReplicationClass in both clusters."""
    yaml_file = Path("workload_data/vrgc.yaml")
    vrgc_yaml_dict = load_yaml_file(yaml_file)[0]

    # Cluster 1
    vrc_c1_dict = get_first_vrc_yaml(args.c1_kubeconfig)
    update_vrgc_from_vrc(vrgc_yaml_dict, vrc_c1_dict)
    ensure_vrgc_exists(args.c1_kubeconfig, vrgc_yaml_dict, "workload_data/vrgc-vm.yaml")

    # Cluster 2
    vrc_c2_dict = get_first_vrc_yaml(args.c2_kubeconfig)
    update_vrgc_from_vrc(vrgc_yaml_dict, vrc_c2_dict)
    ensure_vrgc_exists(args.c2_kubeconfig, vrgc_yaml_dict, "workload_data/vrgc-vm.yaml")
    
def validate_drpolicy(drpolicy_name):
    """Valdiate given drpolicy """
    try:
        subprocess.run(["oc", "get", "drpolicy", f"{drpolicy_name}", "--no-headers"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "Error from server (NotFound):" in stderr or "not found" in stderr:
            sys.exit(f"❌ Given Drpolicy:- {drpolicy_name} does not exisits {e.stderr}")
        else:
            sys.exit(f"❌ An error occurred validating drpolicy name: {e.stderr}")


def main():
    """Main function to execute workload deployment."""
    args = parse_args()
    if args.workload_pvc_type == "mix":
        args.workload_pvc_type="mix-workload"
    args.output_dir = "output_data/"+args.output_dir
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    if args.cg and args.workload_pvc_type == "cephfs":
        sys.exit("❌ Cephfs with CG is not supported")
    if args.workload_pvc_type=="cephfs" and args.workload=="vm":
        sys.exit("❌'vm' workload is not supported with 'cephfs' PVC type.")
    if args.cg:
        create_vrgc(args)
    
    if args.recipe and args.workload_type in ("appset", "sub"):
        sys.exit(f"❌ 'recipe' does not work with {args.workload_type}.")
    
    workload_dict = get_workload_path(args.workload_pvc_type, args.workload)
    workload_path = workload_dict.get("workload_path")
    
    yaml_file = str(Path(f"workload_data/sample_{args.workload_type}_rbd.yaml"))
    all_output_yaml = []

    clusters = get_managed_clusters()
    c1, c2 = args.c1_name, args.c2_name

    if not args.drpolicy_name:
        result = subprocess.run(["oc", "get", "drpolicy", "--no-headers"], capture_output=True, text=True, check=True)
        policy_names = [line.split()[0] for line in result.stdout.strip().split('\n') if line.strip()]
    else:
        validate_drpolicy(args.drpolicy_name)
        policy_names = [args.drpolicy_name]

    clusterset = args.clusterset or get_clusterset_name(c1)
    if args.workload_type == "dist":
        result = subprocess.run(
                ["oc", "--kubeconfig", args.c1_kubeconfig, "get", "ns", "--no-headers", "-o", "name"],
                capture_output=True, text=True, check=True
            )
        current_count = sum(
            1 for line in result.stdout.splitlines()
            if "imp-" in line and args.workload_pvc_type in line and args.workload in line
        )
    c1_dict = {"cluster_name": args.c1_name, "kubeconfig": args.c1_kubeconfig}
    c2_dict = {"cluster_name": args.c2_name, "kubeconfig": args.c2_kubeconfig}
    for i in range(1, args.workload_count + 1):
        if args.workload_type != "dist":
            data = load_yaml_file(yaml_file)
        else:
            git_repo = "https://github.com/red-hat-storage/ocs-workloads.git"
            git_branch = "less_workload"
            if args.repo: 
                git_repo = args.repo
                git_branch = args.repo_branch
                
            clone_and_checkout(git_repo, "ocs-workloads", git_branch)

        policy_name = random.choice(policy_names)

        if args.workload_type == "appset":
            result = subprocess.run(
                ["oc", "get", "ApplicationSet.argoproj.io", "-A", "-o", "name"],
                capture_output=True, text=True
            )
            if args.cg:
                args.workload="bb"
            current_count = sum(
                1 for line in result.stdout.splitlines()
                if args.workload_pvc_type in line and args.workload in line
            )
            dynamic_i = current_count + i
            updated_yaml = update_appset_yaml(data, args.workload_pvc_type, clusterset, args.deploy_on, c1, c2, dynamic_i, workload_path, args.protect_workload, policy_name, args.cg, workload_dict, c1_dict, c2_dict, args.ns_dr_prefix, args.repo_branch)

        elif args.workload_type == "sub":
            result = subprocess.run(
                ["oc", "get", "Subscription.apps.open-cluster-management.io", "-A", "-o", "name"],
                capture_output=True, text=True
            )
            if args.cg:
                args.workload="bb"
            current_count = sum(1 for line in result.stdout.splitlines() if args.workload_pvc_type in line and args.workload in line)
            dynamic_i = current_count + i
            updated_yaml = update_sub_yaml(data, args.workload_pvc_type, clusterset, args.deploy_on, c1, c2, dynamic_i, workload_path, args.protect_workload, policy_name, args.cg, workload_dict, c1_dict, c2_dict, args.ns_dr_prefix, args.repo_branch)
        
        else:
            
            dynamic_i = current_count + i

            
            updated_yaml = deploy_discovered_apps(dynamic_i, workload_path, args.workload_pvc_type, clusterset, args.deploy_on, args.protect_workload, policy_name, c1_dict, c2_dict, args.cg, workload_dict, args.ns_dr_prefix, args.recipe)
        # if args.workload_type != "dist":
        # all_output_yaml.extend(updated_yaml)
        if isinstance(updated_yaml, list):
            # Ensure we're adding the full dictionary to all_output_yaml
            all_output_yaml.extend(updated_yaml)  # updated_yaml is a list of dictionaries
        else:
            # If updated_yaml is a single dictionary, make it a list first
            all_output_yaml.append(updated_yaml)  # updated_yaml is a single dictionary


    # Write combined YAML output
    # if args.workload_type != "dist":
    change_to_script_root()
    ns_dr_prf_data = ""
    if args.ns_dr_prefix:
        ns_dr_prf_data = args.ns_dr_prefix+"_"
    
    single_output_file = Path(args.output_dir) / f"output_{ns_dr_prf_data}{args.workload_type}_{args.workload_pvc_type}_{args.workload}_combined.yaml"
    logger.info(f"Output Dir:- {single_output_file}")
    write_output_yaml(all_output_yaml, single_output_file)


if __name__ == "__main__":
    main()
