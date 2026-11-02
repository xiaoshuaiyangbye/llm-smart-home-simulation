"""Zone-interval SQL is authoritative for energy; API HVAC variables may be instantaneous."""
import sqlite3

ENERGY_SERIES = {
    "electricity_step_j": ("Electricity:Facility", None),
    "lighting_step_j": ("InteriorLights:Electricity", None),
    "cooling_electricity_step_j": ("Cooling:Electricity", None),
    "heating_electricity_step_j": ("Heating:Electricity", None),
    "cooling_thermal_step_j": ("Zone Ideal Loads Supply Air Total Cooling Energy", "AGENTIDEAL"),
    "heating_thermal_step_j": ("Zone Ideal Loads Supply Air Total Heating Energy", "AGENTIDEAL"),
}


def reconcile_energy(database, observations):
    diagnostics = {}
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        for field, (name, key) in ENERGY_SERIES.items():
            rows = connection.execute("""SELECT r.Value,t.Interval,d.Units
                FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
                JOIN Time t USING(TimeIndex)
                WHERE d.Name=? AND (? IS NULL OR d.KeyValue=?) AND d.ReportingFrequency='Zone Timestep'
                AND t.WarmupFlag=0 ORDER BY t.TimeIndex""", (name, key, key)).fetchall()
            if len(rows) != len(observations) or any(interval != 5 or unit != "J" for _, interval, unit in rows):
                raise ValueError(f"Unexpected SQL energy grid/unit: {name}")
            maximum = max(abs(obs[field]-value) for obs, (value, _, _) in zip(observations, rows))
            if "thermal" not in field and maximum > 1e-5:
                raise ValueError(f"API/SQL electricity interval mismatch: {name}: {maximum} J")
            diagnostics[field] = {"api_sql_max_interval_difference_j": maximum, "sql_sum_j": sum(r[0] for r in rows)}
            for obs, (value, _, _) in zip(observations, rows):
                if value < -1e-8:
                    raise ValueError(f"Negative consumption/load: {name}")
                obs[field] = max(0, value)
    return {"canonical_energy_source": "EnergyPlus SQLite Zone Timestep, J, excluding warmup",
            "api_thermal_variables_scope": "may describe last HVAC substep; raw callbacks preserved separately",
            "series": diagnostics}
