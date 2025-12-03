# from kubernetes import client, config
# from config import settings

# # Load cluster config (in-cluster or local)
# try:
#     config.load_incluster_config()
# except:
#     config.load_kube_config()

# apps_api = client.AppsV1Api()
# core_api = client.CoreV1Api()

# def scale_deployment(name: str, replicas: int):
#     body = {"spec": {"replicas": replicas}}
#     return apps_api.patch_namespaced_deployment(
#         name=name,
#         namespace=settings.K8S_NAMESPACE,
#         body=body
#     )

# def restart_deployment(name: str):
#     body = {"spec": {"template": {"metadata": {"annotations": {"smartops/restartedAt": "now"}}}}}
#     return apps_api.patch_namespaced_deployment(
#         name=name,
#         namespace=settings.K8S_NAMESPACE,
#         body=body
#     )

# def get_pods(label_selector=""):
#     return core_api.list_namespaced_pod(
#         namespace=settings.K8S_NAMESPACE,
#         label_selector=label_selector
#     )
