from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app.energyplus.contracts import CalibrationRequest, RunRequest
from app.energyplus.service import DOWNLOADS, service

router = APIRouter(prefix="/api/energyplus", tags=["EnergyPlus"])


def invoke(function, *args):
    try:
        return function(*args)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Resource unavailable for this workspace") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/status")
def status():
    return service.status()


@router.get("/runs")
def list_runs(x_simulation_session: str = Header(default="default")):
    return {"runs": service.list(x_simulation_session)}


@router.post("/runs")
def create_run(request: RunRequest, x_simulation_session: str = Header(default="default")):
    if request.controller == "harness_mock":
        raise HTTPException(400, "Mock controller is disabled in the online application; use harness_real.")
    return invoke(service.create, request, x_simulation_session)


@router.get("/runs/{run_id}")
def get_run(run_id: str, x_simulation_session: str = Header(default="default")):
    return invoke(service.get, run_id, x_simulation_session)


@router.get("/runs/{run_id}/observations")
def observations(run_id: str, x_simulation_session: str = Header(default="default")):
    return {"observations": invoke(service.observations, run_id, x_simulation_session)}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, x_simulation_session: str = Header(default="default")):
    return invoke(service.cancel, run_id, x_simulation_session)


@router.get("/runs/{run_id}/files/{filename:path}")
def download(run_id: str, filename: str, x_simulation_session: str = Header(default="default")):
    if filename not in DOWNLOADS:
        raise HTTPException(404, "Unknown artifact")
    directory = invoke(service.directory, run_id, x_simulation_session)
    path = directory / filename
    if not path.is_file():
        raise HTTPException(404, "Artifact not ready")
    return FileResponse(path, filename=path.name)


@router.post("/calibrations")
def calibrate(request: CalibrationRequest, x_simulation_session: str = Header(default="default")):
    return invoke(service.calibrate, request, x_simulation_session)
