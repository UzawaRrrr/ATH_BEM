"""Optional OpenGL-backed preview host for ATH GUI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tkinter as tk
from typing import Iterable


@dataclass
class PreviewBackendStatus:
    available: bool
    message: str


@dataclass
class OpenGLProbeResult:
    vtk_available: bool
    runtime_available: bool
    tk_bridge_available: bool
    vendor: str = ""
    renderer: str = ""
    version: str = ""
    runtime_error: str = ""
    tk_bridge_error: str = ""
    dll_search_dirs: tuple[str, ...] = ()
    has_rendering_tk_dll: bool = False

    def summary(self) -> str:
        if not self.vtk_available:
            return "VTK 未安裝。"
        parts: list[str] = []
        if self.runtime_available:
            parts.append(f"OpenGL runtime ok ({self.vendor} | {self.renderer} | {self.version})")
        else:
            parts.append(f"OpenGL runtime fail ({self.runtime_error})")
        if self.tk_bridge_available:
            parts.append("VTK Tk bridge ok")
        else:
            parts.append(f"VTK Tk bridge fail ({self.tk_bridge_error})")
        if self.dll_search_dirs:
            parts.append(f"DLL dirs: {len(self.dll_search_dirs)}")
        if not self.has_rendering_tk_dll:
            parts.append("vtkRenderingTk DLL not found")
        return " | ".join(parts)


def _parse_capabilities(caps: str) -> tuple[str, str, str]:
    vendor = ""
    renderer = ""
    version = ""
    for line in str(caps).splitlines():
        text = line.strip()
        if text.lower().startswith("opengl vendor string:"):
            vendor = text.split(":", 1)[1].strip()
        elif text.lower().startswith("opengl renderer string:"):
            renderer = text.split(":", 1)[1].strip()
        elif text.lower().startswith("opengl version string:"):
            version = text.split(":", 1)[1].strip()
    return vendor, renderer, version


def _configure_windows_vtk_dll_paths() -> tuple[str, ...]:
    """Apply Windows DLL search paths commonly needed by VTK wheels/builds."""
    if sys.platform != "win32":
        return ()

    candidates: list[Path] = []
    for env_name in ("VTK_DLL_DIR", "VTK_BIN_DIR"):
        text = os.environ.get(env_name, "").strip()
        if text:
            candidates.append(Path(text))

    candidates.append(Path(sys.prefix) / "Library" / "bin")
    candidates.append(Path(sys.prefix) / "Lib" / "site-packages" / "vtk.libs")
    candidates.append(Path(sys.base_prefix) / "DLLs")
    candidates.append(Path(sys.base_prefix) / "tcl")

    try:
        import vtkmodules  # type: ignore[import-not-found]

        vtkmodules_dir = Path(vtkmodules.__file__).resolve().parent
        candidates.append(vtkmodules_dir)
        candidates.append(vtkmodules_dir.parent / "vtk.libs")
    except Exception:
        pass

    seen: set[str] = set()
    applied: list[str] = []
    for candidate in candidates:
        directory = str(candidate)
        if directory in seen or not candidate.exists():
            continue
        seen.add(directory)
        try:
            os.add_dll_directory(directory)
            applied.append(directory)
        except Exception:
            pass

    if applied:
        current_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ";".join(applied + [current_path]) if current_path else ";".join(applied)
    return tuple(applied)


def _has_rendering_tk_dll(dll_dirs: tuple[str, ...]) -> bool:
    for directory in dll_dirs:
        try:
            files = os.listdir(directory)
        except Exception:
            continue
        for name in files:
            lname = name.lower()
            if lname.startswith("vtkrenderingtk") and lname.endswith(".dll"):
                return True
    return False


def probe_vtk_opengl() -> OpenGLProbeResult:
    """Probe VTK runtime OpenGL capability and Tk interactor bridge availability."""
    dll_dirs = _configure_windows_vtk_dll_paths()
    try:
        import vtk  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local env
        return OpenGLProbeResult(
            vtk_available=False,
            runtime_available=False,
            tk_bridge_available=False,
            runtime_error=str(exc),
            tk_bridge_error=str(exc),
            dll_search_dirs=dll_dirs,
            has_rendering_tk_dll=_has_rendering_tk_dll(dll_dirs),
        )

    result = OpenGLProbeResult(
        vtk_available=True,
        runtime_available=False,
        tk_bridge_available=False,
        dll_search_dirs=dll_dirs,
        has_rendering_tk_dll=_has_rendering_tk_dll(dll_dirs),
    )

    try:
        render_window = vtk.vtkRenderWindow()
        renderer = vtk.vtkRenderer()
        render_window.AddRenderer(renderer)
        render_window.SetOffScreenRendering(1)
        source = vtk.vtkConeSource()
        source.SetResolution(12)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        renderer.AddActor(actor)
        renderer.ResetCamera()
        render_window.Render()
        caps = render_window.ReportCapabilities()
        result.vendor, result.renderer, result.version = _parse_capabilities(caps)
        result.runtime_available = True
    except Exception as exc:  # pragma: no cover - depends on local env
        result.runtime_error = str(exc)

    try:
        from vtkmodules.tk.vtkTkRenderWindowInteractor import vtkTkRenderWindowInteractor  # type: ignore[import-not-found]

        root = tk.Tk()
        root.withdraw()
        host = tk.Frame(root)
        host.grid()
        widget = vtkTkRenderWindowInteractor(host, width=32, height=32)
        widget.GetRenderWindow().Render()
        widget.destroy()
        root.destroy()
        result.tk_bridge_available = True
    except Exception as exc:  # pragma: no cover - depends on local env
        result.tk_bridge_error = str(exc)

    return result


class OpenGLPreviewHost:
    """VTK-based line preview embedded in Tk, with graceful fallback support."""

    def __init__(self, parent: object) -> None:
        _configure_windows_vtk_dll_paths()
        self.parent = parent
        self.available = False
        self.message = "VTK 尚未啟用。"
        self.widget = None
        self._renderer = None
        self._render_window = None
        self._interactor = None
        self._orientation_widget = None
        self._line_actors: list[object] = []
        self._text_actor = None
        self._vtk = None
        self._interaction_sensitivity = 1.0

        try:
            import vtk  # type: ignore[import-not-found]
            from vtkmodules.tk.vtkTkRenderWindowInteractor import vtkTkRenderWindowInteractor  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on local env
            probe = probe_vtk_opengl()
            self.message = f"VTK unavailable: {exc} | {probe.summary()}"
            return

        try:
            self._vtk = vtk
            self.widget = vtkTkRenderWindowInteractor(parent, width=860, height=520)
            try:
                self.widget.configure(background="#0f1725")
            except Exception:
                # Some vtkTk builds do not expose Tk "background" option.
                pass
            self.widget.grid(row=0, column=0, sticky="nsew")

            self._render_window = self.widget.GetRenderWindow()
            # Favor interaction latency over visual niceties in editor preview.
            self._render_window.SetMultiSamples(0)
            self._renderer = vtk.vtkRenderer()
            self._renderer.SetBackground(0.06, 0.10, 0.16)
            try:
                self._renderer.UseFXAAOff()
            except Exception:
                pass
            self._render_window.AddRenderer(self._renderer)
            self._interactor = self._render_window.GetInteractor()
            self._interactor.Initialize()
            self._configure_interaction_profile(vtk)

            axes = vtk.vtkAxesActor()
            marker = vtk.vtkOrientationMarkerWidget()
            marker.SetInteractor(self._interactor)
            marker.SetOrientationMarker(axes)
            marker.SetViewport(0.0, 0.0, 0.18, 0.18)
            marker.SetEnabled(1)
            marker.InteractiveOff()
            self._orientation_widget = marker

            self._text_actor = vtk.vtkTextActor()
            self._text_actor.SetInput("OpenGL preview ready")
            text_property = self._text_actor.GetTextProperty()
            text_property.SetFontSize(16)
            text_property.SetColor(0.80, 0.86, 0.94)
            self._text_actor.SetDisplayPosition(12, 12)
            self._renderer.AddActor2D(self._text_actor)
            self._render_window.Render()
            self.available = True
            self.message = "OpenGL (VTK) 已啟用。"
        except Exception as exc:  # pragma: no cover - depends on local env
            probe = probe_vtk_opengl()
            self.message = f"VTK init failed: {exc} | {probe.summary()}"
            self.available = False

    def _configure_interaction_profile(self, vtk: object) -> None:
        """Set low-latency camera interaction (trackball, no joystick inertia)."""
        if self._interactor is None:
            return
        motion_factor = max(1.0, min(18.0, 6.0 * self._interaction_sensitivity))
        wheel_factor = max(0.15, min(2.5, 0.7 * self._interaction_sensitivity))
        try:
            self._interactor.SetDesiredUpdateRate(120.0)
            self._interactor.SetStillUpdateRate(30.0)
        except Exception:
            pass

        style = self._interactor.GetInteractorStyle()
        if style is not None and style.GetClassName() == "vtkInteractorStyleSwitch":
            try:
                style.SetCurrentStyleToTrackballCamera()
                active = style.GetCurrentStyle()
                if active is not None:
                    if hasattr(active, "SetMotionFactor"):
                        active.SetMotionFactor(motion_factor)
                    if hasattr(active, "SetMouseWheelMotionFactor"):
                        active.SetMouseWheelMotionFactor(wheel_factor)
                return
            except Exception:
                pass

        try:
            trackball = vtk.vtkInteractorStyleTrackballCamera()
            if hasattr(trackball, "SetMotionFactor"):
                trackball.SetMotionFactor(motion_factor)
            if hasattr(trackball, "SetMouseWheelMotionFactor"):
                trackball.SetMouseWheelMotionFactor(wheel_factor)
            self._interactor.SetInteractorStyle(trackball)
        except Exception:
            pass

    def set_interaction_sensitivity(self, sensitivity: float) -> None:
        """Update interactive camera tuning from GUI slider."""
        self._interaction_sensitivity = max(0.3, min(2.5, float(sensitivity)))
        if self._vtk is not None and self._interactor is not None:
            self._configure_interaction_profile(self._vtk)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
        color = hex_color.strip().lstrip("#")
        if len(color) != 6:
            return (0.22, 0.78, 0.70)
        return (
            int(color[0:2], 16) / 255.0,
            int(color[2:4], 16) / 255.0,
            int(color[4:6], 16) / 255.0,
        )

    def _clear_line_actors(self) -> None:
        if not self.available or self._renderer is None:
            return
        for actor in self._line_actors:
            self._renderer.RemoveActor(actor)
        self._line_actors.clear()

    def clear(self, message: str = "No geometry loaded") -> None:
        if not self.available or self._renderer is None:
            return
        self._clear_line_actors()
        if self._text_actor is not None:
            self._text_actor.SetInput(message)
        if self._render_window is not None:
            self._render_window.Render()

    def shutdown(self) -> None:
        """Release Tk/VTK resources in safe order on app shutdown."""
        try:
            if self._render_window is not None:
                self._render_window.Finalize()
        except Exception:
            pass
        try:
            if self.widget is not None:
                self.widget.destroy()
        except Exception:
            pass

    def reset_camera(self) -> None:
        if not self.available or self._renderer is None or self._render_window is None:
            return
        self._renderer.ResetCamera()
        self._render_window.Render()

    def _build_polyline_actor(
        self,
        points: dict[int, tuple[float, float, float]],
        edges: Iterable[tuple[int, int]],
        color: tuple[float, float, float],
    ) -> object | None:
        if self._vtk is None:
            return None
        vtk = self._vtk
        if not points:
            return None

        point_ids = sorted(points.keys())
        index_map = {tag: idx for idx, tag in enumerate(point_ids)}

        vtk_points = vtk.vtkPoints()
        vtk_points.SetNumberOfPoints(len(point_ids))
        for idx, tag in enumerate(point_ids):
            x, y, z = points[tag]
            vtk_points.SetPoint(idx, float(x), float(y), float(z))

        vtk_lines = vtk.vtkCellArray()
        edge_count = 0
        for a, b in edges:
            if a not in index_map or b not in index_map:
                continue
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, index_map[a])
            line.GetPointIds().SetId(1, index_map[b])
            vtk_lines.InsertNextCell(line)
            edge_count += 1
        if edge_count == 0:
            return None

        poly_data = vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetLines(vtk_lines)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(color[0], color[1], color[2])
        actor.GetProperty().SetLineWidth(1.0)
        return actor

    def set_geometry(
        self,
        data: dict[str, object],
        *,
        group_color_map: dict[int, str],
        fallback_color: str,
    ) -> None:
        if not self.available or self._renderer is None or self._render_window is None:
            return
        points = dict(data.get("points", {}))
        edges = list(data.get("edges", []))
        group_edges = {
            int(group_id): list(group_data)
            for group_id, group_data in dict(data.get("group_edges", {})).items()
        }

        self._clear_line_actors()
        added = 0
        if group_edges:
            for group_id in sorted(group_edges):
                color = self._hex_to_rgb(group_color_map.get(group_id, fallback_color))
                actor = self._build_polyline_actor(points, group_edges[group_id], color)
                if actor is not None:
                    self._renderer.AddActor(actor)
                    self._line_actors.append(actor)
                    added += 1
        else:
            actor = self._build_polyline_actor(points, edges, self._hex_to_rgb(fallback_color))
            if actor is not None:
                self._renderer.AddActor(actor)
                self._line_actors.append(actor)
                added += 1

        if self._text_actor is not None:
            if added > 0:
                self._text_actor.SetInput("OpenGL preview")
            else:
                self._text_actor.SetInput("No drawable geometry")

        if added > 0:
            self._renderer.ResetCamera()
        self._render_window.Render()
