# Standards and Evaluation Notes

This project uses simplified comfort and energy metrics for software simulation. The configured thresholds are intended for repeatable local evaluation, not building design, inspection, certification, or health/safety decisions.

> Retrieval summary: software-simulation comfort standards for indoor temperature, humidity, illuminance, energy use, target ranges, and task-completion evaluation.

## Config Files

Thresholds and room/device parameters are stored in:

```text
backend/app/config/standards.yaml
backend/app/config/rooms.yaml
backend/app/config/devices.yaml
```

## Evaluation Areas

- lighting comfort
- thermal comfort
- humidity comfort
- energy use
- task completion
- feedback correction count

## Interpretation

The feedback agent uses target ranges and current environment state to determine whether a task has been completed. Temperature and humidity can require simulated convergence time, so completion status should be interpreted together with comfort scores and final room state.

Baseline policies are implemented as deterministic comparison logic. They are useful for relative software experiments, but they are not historical household usage data or real utility-cost estimates.

## Practical Boundary

The platform maps standards-inspired thresholds into a simplified simulation model. It does not implement formal measurement procedures, sensor calibration, sampling plans, or engineering compliance checks.
