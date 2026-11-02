"""User-supplied point calibration; source authenticity is never inferred."""
from app.energyplus.contracts import CalibrationRequest


def fit_calibration(request: CalibrationRequest):
    points = sorted(request.points, key=lambda p: p.dimming_fraction)
    train = points[::2]
    holdout = points[1::2]

    def fit(name):
        xs = [p.dimming_fraction for p in train]
        ys = [getattr(p, name) for p in train]
        mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator <= 0:
            raise ValueError("Training subset must contain distinct dimming levels")
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
        intercept = mean_y - slope * mean_x
        if slope <= 0 or intercept < -max(1, mean_y * 0.1):
            raise ValueError(f"Non-physical linear response for {name}; inspect measurements")
        errors = [max(0, intercept + slope * p.dimming_fraction) - getattr(p, name) for p in holdout]
        return {"slope": slope, "intercept": intercept,
                "holdout_mae": sum(abs(x) for x in errors) / len(errors),
                "holdout_rmse": (sum(x*x for x in errors) / len(errors)) ** 0.5}
    return {"method": "linear least squares, sorted alternating split", "train_count": len(train),
            "holdout_count": len(holdout), "illuminance": fit("electric_illuminance_lux"),
            "power": fit("power_w"), "source_description": request.source_description,
            "sensor_location": request.sensor_location, "ambient_subtracted": True,
            "source_authenticity": "user_declared_not_independently_verified",
            "boundary": "point response only; not a room illuminance-distribution validation"}
