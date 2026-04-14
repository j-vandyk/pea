# Mobility Data → Graph Analysis Pipeline
## DCI Trip Extraction + city2graph Implementation Guide

---

## Overview

This document covers how to transform a large-scale mobility dataset (hundreds of millions of raw location observations) into a graph representation suitable for community detection and Graph Neural Networks. The two-stage approach:

1. **Trip extraction** — apply the Divide, Conquer and Integrate (DCI) framework (Wang et al. 2019) to convert raw pings into structured origin–destination trips
2. **Graph construction** — feed the resulting OD matrix into city2graph to build a zone-level graph for downstream analysis

---

## Core References

### Wang et al. (2019) — The DCI Framework

> *Extracting Trips from Multi-Sourced Data for Mobility Pattern Analysis: An App-Based Data Example*
> Transportation Research Part C: Emerging Technologies, vol. 105, pp. 183–202
> DOI: [10.1016/j.trc.2019.05.028](https://doi.org/10.1016/j.trc.2019.05.028) | arXiv: [1912.01835](https://arxiv.org/abs/1912.01835) | PMC: [PMC7405914](https://pmc.ncbi.nlm.nih.gov/articles/PMC7405914/)

The DCI framework solves the core problem of multi-sourced mobility data: GPS, WiFi, and cell-tower signals have wildly different spatial resolutions (5 m vs. 1,000 m) and temporal densities. Applying a single trip-extraction method across all source types produces unreliable stays. DCI handles this in three steps:

| Step | What happens |
|------|-------------|
| **Divide** | Partition the raw observation stream by `source_type` (GPS, WiFi, cell) — each partition has homogeneous spatial/temporal properties |
| **Conquer** | Apply source-appropriate stay detection independently on each partition. A *stay* is detected when a device does not move beyond a distance threshold (5 m for GPS, 1,000 m for cell) for ≥5 minutes |
| **Integrate** | Merge stay lists across partitions using a spatiotemporal overlap algorithm. A *trip* is then defined as a pair of consecutive stays: (origin, destination, departure_time, arrival_time) |

Validated against manually labelled app-based data; outperforms a GPS-tuned SVM baseline.

### city2graph (v0.3.1, March 2026)

> Python library for converting geospatial datasets into graph structures for GNNs and spatial network analysis
> GitHub: [c2g-dev/city2graph](https://github.com/c2g-dev/city2graph) | PyPI: [city2graph](https://pypi.org/project/city2graph/) | Docs: [city2graph.net](https://city2graph.net/latest/)

Provides an integrated interface across GeoPandas, NetworkX, and PyTorch Geometric. The key function for this use case is `od_matrix_to_graph()`, which accepts an OD edgelist or adjacency matrix and returns two GeoDataFrames (nodes and edges) ready for graph algorithms or GNN training.

---

## Literature Review

The following papers represent the closest precedent for the combined DCI-extraction → graph-analysis pipeline.

### 1. Resolving Urban Mobility Networks from Individual Travel Graphs
**Xu et al. (2020)** | *Computers, Environment and Urban Systems*
[doi.org/10.1016/j.compenvurbsys.2021.101706](https://www.sciencedirect.com/science/article/abs/pii/S0264275120314256)

The most direct precedent at comparable scale. Aggregates individual-level trip sequences extracted from massive mobile phone tracking data into graph motifs, then constructs a global weighted directed graph (zones as nodes, trip counts as edge weights). Applies community detection to reveal the functional spatial structure of the city. Demonstrates the full pipeline from individual traces to graph-level insights without requiring individual-level privacy-sensitive data in the final output.

### 2. Communities in Urban Mobility Networks via Multi-Layer Graphs
**Cats et al. (2017)** | *Transportation Research Part C*
[doi.org/10.1016/j.trc.2018.10.007](https://www.sciencedirect.com/science/article/pii/S2352146517309675)

Combines three data sources — bus GPS, smart card transactions, and Bluetooth detectors — into a multi-layer graph, analogous to DCI's three-way source partition. Runs layer-by-layer community detection, returning geographically coherent mobility zones. Validates that multi-source integration produces more stable communities than any single source alone. Directly relevant to city2graph's heterogeneous graph support.

### 3. Human Mobility Networks Reveal Increased Segregation in Large Cities
**Moro et al. (2023)** | *Nature*
[doi.org/10.1038/s41586-023-06757-3](https://www.nature.com/articles/s41586-023-06757-3)

Phone mobility data → OD flow graph → graph embeddings + community detection → socioeconomic segregation analysis, validated against US census ground truth. Demonstrates the analytic value of this pipeline for social science applications: the graph reveals latent residential vs. activity-space segregation patterns that are invisible in raw data. A benchmark for how to interpret community structure from mobility graphs.

### 4. Urban Delineation Through Commute Networks via GNN
**Meng et al. (2024/2025)** | *PLOS Complex Systems*
[doi.org/10.1371/journal.pcsy.0000061](https://journals.plos.org/complexsystems/article?id=10.1371/journal.pcsy.0000061)

Commute OD flows → graph → PyTorch Geometric GNN (GraphSAGE) embeddings → node clustering to identify functional urban areas and distinguish socioeconomic groups. Technically the closest to the proposed city2graph + GNN workflow. Shows that GNN-derived zone embeddings capture more nuanced structure than simple community detection alone.

### 5. Nation-Wide Human Mobility Prediction via GNN
**Yabe et al. (2021)** | *PMC / Scientific Reports*
[pmc.ncbi.nlm.nih.gov/articles/PMC8288072](https://pmc.ncbi.nlm.nih.gov/articles/PMC8288072/)

Constructs a national-scale OD graph and trains a GNN to predict inter-region mobility flows, accounting for latent geographic relationships not captured by simple gravity models. Validates that graph-based approaches generalise to datasets with hundreds of millions of observations — the aggregation to zone level is the key scalability step.

### 6. Dynamic Mobility Patterns via Traffic Flow Community Detection
**Li et al. (2024)** | *International Journal of Geographical Information Science*
[doi.org/10.1080/19475683.2024.2324393](https://www.tandfonline.com/doi/full/10.1080/19475683.2024.2324393)

Constructs temporal mobility graphs from traffic flow data and compares Louvain, Infomap, and spectral clustering across multiple time windows. Best practice reference for algorithm selection and temporal aggregation strategy on mobility graphs. Key finding: daily aggregation produces more stable communities than hourly; Louvain consistently yields the highest modularity.

### 7. Spatio-Temporal Community Detection from CDR Data
*IEEE (2017)*
[ieeexplore.ieee.org/document/8255177](https://ieeexplore.ieee.org/document/8255177/)

Builds a mobility graph directly from Call Detail Records (cell tower → cell tower transitions), then applies spatio-temporal community detection to find urban districts. Highlights the trade-off between CDR spatial coarseness and scale: CDR can cover entire populations but loses the within-district spatial detail that GPS provides. The DCI framework addresses exactly this by combining both.

---

## Pipeline Architecture

```
Raw observations
(user_id, timestamp, lat, lon, source_type)
         │
         │  ┌─────────────────────────────────────────┐
         ▼  │         DCI Framework                   │
    ┌────────────────┐                                 │
    │    DIVIDE      │  Partition by source_type       │
    │  GPS / WiFi /  │  (homogeneous spatial res.)     │
    │  cell tower    │                                 │
    └───────┬────────┘                                 │
            │                                          │
    ┌───────▼────────┐                                 │
    │    CONQUER     │  Stay detection per partition   │
    │  detect_stays()│  (source-appropriate thresholds)│
    └───────┬────────┘                                 │
            │                                          │
    ┌───────▼────────┐                                 │
    │   INTEGRATE    │  Spatiotemporal stay merging    │
    │ integrate_stays│  Trip = consecutive stay pair   │
    └───────┬────────┘                                 │
            └─────────────────────────────────────────┘
         │
         ▼
  Trips (user_id, origin_lat, origin_lon,
         dest_lat, dest_lon, depart, arrive)
         │
         │  Spatial join to zone geometries
         ▼
  Zone-level OD edgelist
  (origin_zone_id, dest_zone_id, flow_count)
         │
         │  city2graph.od_matrix_to_graph()
         ▼
  nodes_gdf + edges_gdf  (GeoDataFrames)
         │
         ├──────────────────────────────────┐
         ▼                                  ▼
  NetworkX                         PyTorch Geometric
  Louvain community detection      GNN (GraphSAGE / GAT)
  Centrality / flow metrics        Zone embeddings
  Urban district delineation       Flow prediction
```

---

## Implementation

### Installation

```bash
pip install city2graph                          # core (NetworkX, GeoPandas)
pip install city2graph[cpu]                     # + PyTorch Geometric (CPU)
# or for GPU:
pip install city2graph[cu126]                   # CUDA 12.6
```

### Stage 1 — DCI Trip Extraction

```python
import pandas as pd
import numpy as np

# Source-appropriate stay detection thresholds (distance_m, min_duration_s)
THRESHOLDS = {
    "GPS":  {"dist_m": 5,    "min_s": 300},
    "WiFi": {"dist_m": 50,   "min_s": 300},
    "cell": {"dist_m": 1000, "min_s": 300},
}

def detect_stays(user_df: pd.DataFrame, dist_m: float, min_s: float) -> pd.DataFrame:
    """
    Identify stay periods in a single user's location stream.
    user_df must be sorted by timestamp and contain lat, lon columns.
    Returns DataFrame of stays with start_time, end_time, centroid lat/lon.
    """
    # ... implement using haversine distance + sliding window
    pass

def integrate_stays(stays: pd.DataFrame) -> pd.DataFrame:
    """
    Merge stays from different source partitions for one user.
    Resolves overlapping or contradictory stays using spatiotemporal proximity.
    See Wang et al. 2019 Section 3.3 for the full algorithm.
    """
    pass

def stays_to_trips(stays: pd.DataFrame) -> pd.DataFrame:
    """Convert sorted stay sequence into (origin, destination) trip pairs."""
    trips = stays.copy()
    trips["dest_lat"]  = trips["lat"].shift(-1)
    trips["dest_lon"]  = trips["lon"].shift(-1)
    trips["arrive"]    = trips["start_time"].shift(-1)
    trips = trips.rename(columns={"lat": "origin_lat", "lon": "origin_lon",
                                   "end_time": "depart"})
    return trips.dropna(subset=["dest_lat"]).iloc[:-1]

def dci_extract_trips(df: pd.DataFrame) -> pd.DataFrame:
    """Full DCI pipeline for one user's observations."""
    results = []
    for src, grp in df.groupby("source_type"):
        thresh = THRESHOLDS.get(src, THRESHOLDS["cell"])
        stays = detect_stays(grp.sort_values("timestamp"), **thresh)
        results.append(stays)
    merged = integrate_stays(pd.concat(results).sort_values("start_time"))
    return stays_to_trips(merged)
```

**Scaling to hundreds of millions of observations** — the DCI stay detection step is embarrassingly parallel by `user_id`. Use Dask or PySpark:

```python
import dask.dataframe as dd

ddf = dd.read_parquet("observations/*.parquet")
trips = (
    ddf
    .groupby("user_id")
    .apply(dci_extract_trips, meta=trip_schema)
    .compute()
)
```

### Stage 2 — Aggregate to Zone-Level OD Matrix

```python
import geopandas as gpd

# Load zone geometries (admin boundaries, H3 cells, or custom grid)
zones_gdf = gpd.read_file("data/zones.geojson")   # must have a unique zone_id column

# Spatial join: assign each trip endpoint to a zone
origins = gpd.GeoDataFrame(
    trips, geometry=gpd.points_from_xy(trips.origin_lon, trips.origin_lat), crs="EPSG:4326"
)
origins = gpd.sjoin(origins, zones_gdf[["zone_id", "geometry"]], how="left", predicate="within")
origins = origins.rename(columns={"zone_id": "origin_zone_id"})

dests = gpd.GeoDataFrame(
    trips, geometry=gpd.points_from_xy(trips.dest_lon, trips.dest_lat), crs="EPSG:4326"
)
dests = gpd.sjoin(dests, zones_gdf[["zone_id", "geometry"]], how="left", predicate="within")
dests = dests.rename(columns={"zone_id": "dest_zone_id"})

trips["origin_zone_id"] = origins["origin_zone_id"].values
trips["dest_zone_id"]   = dests["dest_zone_id"].values

# Aggregate to OD edgelist
od_edgelist = (
    trips
    .dropna(subset=["origin_zone_id", "dest_zone_id"])
    .groupby(["origin_zone_id", "dest_zone_id"])
    .size()
    .reset_index(name="flow")
)
# Result: DataFrame with columns [origin_zone_id, dest_zone_id, flow]
```

### Stage 3 — Build Graph with city2graph

```python
import city2graph as c2g

nodes_gdf, edges_gdf = c2g.od_matrix_to_graph(
    matrix_data=od_edgelist,
    zones_gdf=zones_gdf,
    zone_id_col="zone_id",
    matrix_type="edgelist",
    source_col="origin_zone_id",
    target_col="dest_zone_id",
    weight_cols=["flow"],
    directed=True,
    threshold=10,               # drop edges with fewer than 10 trips (noise floor)
    threshold_col="flow",
    compute_edge_geometry=True,
)
# nodes_gdf: one row per zone — geometry + any node-level features you attach
# edges_gdf: one row per OD pair — geometry + flow weight
```

You can attach additional node features (population, land use, POI counts) to `nodes_gdf` before passing to a GNN:

```python
nodes_gdf = nodes_gdf.merge(zone_features_df, on="zone_id", how="left")
```

### Stage 4a — Community Detection (NetworkX)

```python
import networkx as nx
from networkx.algorithms.community import louvain_communities

G = nx.from_pandas_edgelist(
    edges_gdf,
    source="source",
    target="target",
    edge_attr="flow",
    create_using=nx.DiGraph(),
)

# Louvain (best modularity for weighted mobility graphs — Li et al. 2024)
communities = louvain_communities(G, weight="flow", seed=42)

# Map community membership back to zones
zone_community = {}
for i, comm in enumerate(communities):
    for zone_id in comm:
        zone_community[zone_id] = i

nodes_gdf["community"] = nodes_gdf["zone_id"].map(zone_community)
```

### Stage 4b — GNN Embeddings (PyTorch Geometric)

```python
import torch
from torch_geometric.nn import SAGEConv

# Convert to PyG Data object via city2graph
pyg_data = c2g.to_pyg(nodes_gdf, edges_gdf)

class MobilityGraphSAGE(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index).relu()
        x = self.conv2(x, edge_index)
        return x

model = MobilityGraphSAGE(
    in_channels=pyg_data.x.shape[1],
    hidden_channels=64,
    out_channels=32,
)
embeddings = model(pyg_data.x, pyg_data.edge_index)
# embeddings: (n_zones, 32) — cluster these for zone delineation
```

---

## Scale Considerations

| Stage | Recommended tool | Notes |
|---|---|---|
| Stay detection | Dask / PySpark | Embarrassingly parallel by `user_id` |
| Stay integration | Pandas (per user) | O(n²) within user — manageable |
| OD aggregation | Dask groupby | Reduce to zone level as early as possible |
| Zone spatial join | GeoPandas + STRtree | Use spatial index; avoid row-wise loops |
| Graph construction | city2graph | Zone-level → typically 1k–100k nodes |
| Community detection | NetworkX Louvain | Scales to millions of edges |
| GNN training | PyTorch Geometric | GPU-accelerated; zone graph fits in memory |

The critical insight: DCI reduces hundreds of millions of raw pings to millions of trips; aggregating to zones reduces further to a graph with thousands of nodes — making all downstream graph algorithms tractable on a single machine.

---

## Validation

| Check | How |
|---|---|
| DCI output quality | Sample 100 users; manually inspect stay/trip boundaries against raw traces |
| OD matrix plausibility | Compare total trip counts by time-of-day against known commute patterns or HTS data |
| Graph connectivity | `nx.is_weakly_connected(G)`; inspect giant component fraction |
| Community quality | Modularity score (`nx.community.modularity`); map communities against known admin boundaries |
| GNN embeddings | Hold out a time window; evaluate flow prediction RMSE vs. gravity model baseline |

---

## References

- Wang, F. et al. (2019). Extracting trips from multi-sourced data for mobility pattern analysis. *Transportation Research Part C*, 105, 183–202. [PMC7405914](https://pmc.ncbi.nlm.nih.gov/articles/PMC7405914/)
- Xu, Y. et al. (2020). Resolving urban mobility networks from individual travel graphs using massive-scale mobile phone tracking data. *Computers, Environment and Urban Systems*. [doi.org/10.1016/j.compenvurbsys.2021.101706](https://www.sciencedirect.com/science/article/abs/pii/S0264275120314256)
- Cats, O. et al. (2017). Identification of communities in urban mobility networks using multi-layer graphs of network traffic. *Transportation Research Part C*. [doi.org/10.1016/j.trc.2018.10.007](https://www.sciencedirect.com/science/article/pii/S2352146517309675)
- Moro, E. et al. (2023). Human mobility networks reveal increased segregation in large cities. *Nature*. [doi.org/10.1038/s41586-023-06757-3](https://www.nature.com/articles/s41586-023-06757-3)
- Meng, C. et al. (2024/2025). Urban delineation through the lens of commute networks. *PLOS Complex Systems*. [doi.org/10.1371/journal.pcsy.0000061](https://journals.plos.org/complexsystems/article?id=10.1371/journal.pcsy.0000061)
- Yabe, T. et al. (2021). Nation-wide human mobility prediction based on graph neural networks. *Scientific Reports*. [PMC8288072](https://pmc.ncbi.nlm.nih.gov/articles/PMC8288072/)
- Li, Z. et al. (2024). Exploring dynamic urban mobility patterns from traffic flow data using community detection. *IJGIS*. [doi.org/10.1080/19475683.2024.2324393](https://www.tandfonline.com/doi/full/10.1080/19475683.2024.2324393)
