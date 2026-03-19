"""Job schema and validation for the external ATH Bempp solver."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _list_of_ints(value: object) -> list[int]:
    if value is None:
        return []
    return [int(item) for item in value]


def _list_of_floats(value: object) -> list[float]:
    if value is None:
        return []
    return [float(item) for item in value]


def _list_of_vectors(value: object) -> list[list[float]]:
    if value is None:
        return []
    vectors: list[list[float]] = []
    for vector in value:
        parts = [float(item) for item in vector]
        if len(parts) != 3:
            raise ValueError("Each source_direction entry must contain exactly 3 numeric values.")
        vectors.append(parts)
    return vectors


@dataclass
class BemJob:
    mesh_file: str
    mesh_file_wsl: str
    mesh_scale_to_meter: float = 0.001
    solver_mode: str = "exterior_velocity_bc"
    source_groups: list[int] = field(default_factory=list)
    wall_groups: list[int] = field(default_factory=list)
    interface_groups: list[int] = field(default_factory=list)
    ignore_groups: list[int] = field(default_factory=list)
    source_gain: list[float] = field(default_factory=lambda: [1.0])
    source_direction: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0, 1.0]])
    velocity_model: str = "uniform"
    f1: float = 200.0
    f2: float = 20000.0
    num_freq: int = 48
    rho0: float = 1.21
    c0: float = 343.0
    mic_distance: float = 5.0
    plane: str = "XZ"
    theta_count: int = 361
    reference_pressure: float = 2.8284271247461903e-05
    export_png: bool = True
    export_boundary_pressure: bool = False
    job_path: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, payload: dict[str, object], *, job_path: Path | None = None) -> "BemJob":
        job = cls(
            mesh_file=str(payload["mesh_file"]),
            mesh_file_wsl=str(payload.get("mesh_file_wsl", payload["mesh_file"])),
            mesh_scale_to_meter=float(payload.get("mesh_scale_to_meter", 0.001)),
            solver_mode=str(payload.get("solver_mode", "exterior_velocity_bc")),
            source_groups=_list_of_ints(payload.get("source_groups")),
            wall_groups=_list_of_ints(payload.get("wall_groups")),
            interface_groups=_list_of_ints(payload.get("interface_groups")),
            ignore_groups=_list_of_ints(payload.get("ignore_groups")),
            source_gain=_list_of_floats(payload.get("source_gain", [1.0])),
            source_direction=_list_of_vectors(payload.get("source_direction", [[0.0, 0.0, 1.0]])),
            velocity_model=str(payload.get("velocity_model", "uniform")),
            f1=float(payload.get("f1", 200.0)),
            f2=float(payload.get("f2", 20000.0)),
            num_freq=int(payload.get("num_freq", 48)),
            rho0=float(payload.get("rho0", 1.21)),
            c0=float(payload.get("c0", 343.0)),
            mic_distance=float(payload.get("mic_distance", 5.0)),
            plane=str(payload.get("plane", "XZ")).upper(),
            theta_count=int(payload.get("theta_count", 361)),
            reference_pressure=float(payload.get("reference_pressure", 2.8284271247461903e-05)),
            export_png=bool(payload.get("export_png", True)),
            export_boundary_pressure=bool(payload.get("export_boundary_pressure", False)),
            job_path=job_path,
        )
        job.validate()
        return job

    @classmethod
    def from_json_file(cls, path: Path) -> "BemJob":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")), job_path=path)

    @property
    def job_dir(self) -> Path:
        if self.job_path is None:
            raise ValueError("This job instance is not attached to a job.json path.")
        return self.job_path.parent

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("job_path", None)
        return data

    def expanded_source_gain(self) -> list[float]:
        if len(self.source_gain) == 1:
            return self.source_gain * len(self.source_groups)
        return list(self.source_gain)

    def expanded_source_direction(self) -> list[list[float]]:
        if len(self.source_direction) == 1:
            return self.source_direction * len(self.source_groups)
        return [list(vector) for vector in self.source_direction]

    def validate(self) -> None:
        if not self.mesh_file:
            raise ValueError("mesh_file is required.")
        if not self.mesh_file_wsl:
            raise ValueError("mesh_file_wsl is required.")
        if self.solver_mode != "exterior_velocity_bc":
            raise ValueError(f"Unsupported solver_mode: {self.solver_mode}")
        if self.velocity_model != "uniform":
            raise ValueError(f"Unsupported velocity_model: {self.velocity_model}")
        if not self.source_groups:
            raise ValueError("At least one source group is required.")
        if any(group <= 0 for group in self.source_groups):
            raise ValueError("source_groups must use positive integer IDs.")
        if any(group <= 0 for group in self.wall_groups + self.interface_groups + self.ignore_groups):
            raise ValueError("wall/interface/ignore groups must use positive integer IDs.")
        if self.mesh_scale_to_meter <= 0:
            raise ValueError("mesh_scale_to_meter must be greater than zero.")
        if self.f1 <= 0 or self.f2 < self.f1:
            raise ValueError("Frequency range must satisfy `0 < f1 <= f2`.")
        if self.num_freq < 1:
            raise ValueError("num_freq must be at least 1.")
        if self.rho0 <= 0 or self.c0 <= 0:
            raise ValueError("rho0 and c0 must be greater than zero.")
        if self.mic_distance <= 0:
            raise ValueError("mic_distance must be greater than zero.")
        if self.theta_count < 3:
            raise ValueError("theta_count must be at least 3.")
        if self.plane not in {"XZ", "YZ"}:
            raise ValueError("plane must be either `XZ` or `YZ`.")
        if self.reference_pressure <= 0:
            raise ValueError("reference_pressure must be greater than zero.")
        if len(self.source_gain) not in {1, len(self.source_groups)}:
            raise ValueError("source_gain must contain either 1 value or one value per source group.")
        if len(self.source_direction) not in {1, len(self.source_groups)}:
            raise ValueError("source_direction must contain either 1 vector or one vector per source group.")

        source_set = set(self.source_groups)
        wall_set = set(self.wall_groups)
        ignore_set = set(self.ignore_groups)
        interface_set = set(self.interface_groups)

        if source_set & wall_set:
            raise ValueError("source_groups and wall_groups must not overlap.")
        if source_set & ignore_set:
            raise ValueError("source_groups and ignore_groups must not overlap.")
        if wall_set & ignore_set:
            raise ValueError("wall_groups and ignore_groups must not overlap.")
        if interface_set & ignore_set:
            raise ValueError("interface_groups and ignore_groups must not overlap.")
