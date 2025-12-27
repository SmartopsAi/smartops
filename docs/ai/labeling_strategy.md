# Labeling Strategy – SmartOps AI

SmartOps uses ERP Simulator anomaly modes as ground truth labels.

## Ground Truth Signal

- Source metric: `erp_simulator_modes_enabled`

## Label Definition

- modes_enabled == 0 → NORMAL (label = 0)
- modes_enabled > 0 → ANOMALY (label = 1)

## Usage

- Used for training validation
- Used to measure false positives and recall
- Used during chaos experiments

## Justification

ERP Simulator explicitly controls anomaly injection, making this a reliable
and reproducible labeling mechanism for research evaluation.
