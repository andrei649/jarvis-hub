# WorldView — KEDA lag-scaled consumers (ticket H19.1.5)

Kubernetes manifests for the ingestion consumers + **KEDA `ScaledObject`s** that autoscale
each consumer on its **Kafka/Redpanda consumer-group lag**. When a group falls behind the
firehose, KEDA adds replicas; when it catches up, it scales back to `minReplicaCount`.

```
Redpanda topics ──► consumer group ──► Deployment ──(lag)──► KEDA kafka scaler ──► HPA replicas
  osint.adsb/ais/ew     live-writer       live-writer        lagThreshold 10000     1..10
  osint.adsb/ais/...    history-writer    history-writer     lagThreshold 20000/5000 1..8
  osint.recon           recon-writer      recon-writer       lagThreshold 2000      1..4
```

## Files

| File | Contents |
| --- | --- |
| `namespace.yaml` | `worldview` namespace |
| `consumers.yaml` | one Deployment per consumer role (live / history / recon writer) |
| `scaledobjects.yaml` | one KEDA `ScaledObject` per Deployment, kafka lag triggers |
| `kustomization.yaml` | applies all three with `kubectl apply -k` |

## How the lag trigger maps to the consumer groups

Group names are taken verbatim from the app (`backend-api/src/consumers/*.ts`):

| Deployment | `consumerGroup` | Topics (triggers) | `lagThreshold` | min/max |
| --- | --- | --- | --- | --- |
| `live-writer` | `live-writer` | osint.adsb, osint.ais, osint.ew | 10000 each | 1 / 10 |
| `history-writer` | `history-writer` | osint.adsb, osint.ais, osint.context | 20000 / 20000 / 5000 | 1 / 8 |
| `recon-writer` | `recon-writer` | osint.recon | 2000 | 1 / 4 |

KEDA's `kafka` scaler compares the group's **committed offset** to each topic's **end
offset**; desired replicas ≈ `ceil(lag / lagThreshold)` per trigger, and KEDA takes the
**max across triggers**. Thresholds mirror the observability lag alarm tiers (warn at 50k /
crit at 250k in `deploy/observability/alerts.yml`) — KEDA reacts *before* those fire:
live-writer (latency-critical live map) scales most aggressively; recon-writer (low-volume,
CPU-bound prediction stream) scales on a small threshold but a low cap.

> Multi-topic note: live-writer also subscribes to `osint.tle` and history-writer to
> `osint.tle`; these are low-rate so they're omitted as scale triggers (adding a trigger only
> ever *raises* desired replicas). Add a `kafka` trigger block if you want them to count.

## Run locally (kind / k3s + KEDA via helm)

```bash
# 1) A local cluster
kind create cluster --name worldview          # or: k3d cluster create worldview
# or k3s:  curl -sfL https://get.k3s.io | sh -

# 2) Install KEDA (provides the keda.sh/v1alpha1 ScaledObject CRD + the kafka scaler)
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace --version 2.14.0

# 3) Apply the WorldView ingestion stack
kubectl apply -k deploy/k8s/

# 4) Verify
kubectl -n worldview get deploy,scaledobject
kubectl -n worldview get hpa            # KEDA creates an HPA per ScaledObject
kubectl get crd scaledobjects.keda.sh   # confirms KEDA CRDs are installed
```

To tear down: `kubectl delete -k deploy/k8s/` then `helm uninstall keda -n keda`.

## Prerequisites in-cluster (TODOs)

These manifests are the autoscaling deliverable; making pods actually *do work* needs:

- **A reachable Redpanda broker in-cluster.** `bootstrapServers` and the consumers'
  `KAFKA_BROKERS` point at `redpanda.worldview.svc.cluster.local:29092` (the PLAINTEXT
  listener). The local `docker-compose.yml` Redpanda is **not** in the cluster — run Redpanda
  in k8s (e.g. the Redpanda Helm chart / operator) or expose the host broker as a Service +
  Endpoints. TODO(infra): set the real broker DNS in `consumers.yaml` and `scaledobjects.yaml`.
- **A real consumer image.** `consumers.yaml` uses the placeholder
  `ghcr.io/worldview/backend-api:TODO`. TODO(app): publish the backend-api image and pin the
  tag. Ideally a **consumer-only entrypoint** so each pod runs just its writer (the
  `ENABLE_*` flags are already set per Deployment) without binding the HTTP server.
- **Health/readiness port (optional).** Probes are intentionally omitted — the consumers have
  no HTTP port in consumer-only mode. TODO(app): expose a liveness/readiness endpoint and add
  probes for safer rollouts.

## Why meaningful autoscaling needs real load

KEDA scales on **actual consumer-group lag**, which only exists when producers outpace
consumers. On an idle local cluster every group sits at lag 0, so KEDA holds every Deployment
at `minReplicaCount: 1` — correct, but not visibly "autoscaling". To see scale-out you need a
real firehose (ingestion workers producing to `osint.*`) or a synthetic load. The
**manifests + the lag triggers are the deliverable**; observing replica counts climb requires
load + a real in-cluster broker.

## Image / chart pins

| Component | Pin |
| --- | --- |
| KEDA helm chart | 2.14.0 |
| consumer image | `ghcr.io/worldview/backend-api:TODO` (placeholder — pin a real tag) |
