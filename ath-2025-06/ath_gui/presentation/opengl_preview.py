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
        self._marker_actors: list[object] = []
        self._normal_actors: list[object] = []
        self._legend_actors: list[object] = []
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
        for actor in self._marker_actors:
            self._renderer.RemoveActor(actor)
        self._marker_actors.clear()
        for actor in self._normal_actors:
            self._renderer.RemoveActor(actor)
        self._normal_actors.clear()
        for actor in self._legend_actors:
            self._renderer.RemoveActor2D(actor)
        self._legend_actors.clear()

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

    @staticmethod
    def _group_centroid(
        points: dict[int, tuple[float, float, float]],
        edges: list[tuple[int, int]],
    ) -> tuple[float, float, float] | None:
        if not edges:
            return None
        tags: set[int] = set()
        sample_step = max(1, len(edges) // 2400)
        for index, (a, b) in enumerate(edges):
            if index % sample_step != 0:
                continue
            if a in points:
                tags.add(a)
            if b in points:
                tags.add(b)
        if not tags:
            return None

        sx = 0.0
        sy = 0.0
        sz = 0.0
        count = 0
        for tag in tags:
            x, y, z = points[tag]
            sx += float(x)
            sy += float(y)
            sz += float(z)
            count += 1
        if count <= 0:
            return None
        return (sx / count, sy / count, sz / count)

    def _add_group_marker(
        self,
        group_id: int,
        position: tuple[float, float, float],
        color: tuple[float, float, float],
        radius: float,
    ) -> None:
        if self._vtk is None or self._renderer is None:
            return
        vtk = self._vtk
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(float(position[0]), float(position[1]), float(position[2]))
        sphere.SetRadius(float(radius))
        sphere.SetThetaResolution(14)
        sphere.SetPhiResolution(14)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(color[0], color[1], color[2])
        actor.GetProperty().SetOpacity(0.95)
        self._renderer.AddActor(actor)
        self._marker_actors.append(actor)

        if hasattr(vtk, "vtkBillboardTextActor3D"):
            label = vtk.vtkBillboardTextActor3D()
            label.SetInput(f"G{group_id}")
            label.SetPosition(float(position[0]), float(position[1]), float(position[2] + (radius * 1.4)))
            text_prop = label.GetTextProperty()
            text_prop.SetColor(color[0], color[1], color[2])
            text_prop.SetFontSize(16)
            self._renderer.AddActor(label)
            self._marker_actors.append(label)

    def _add_group_legend(
        self,
        group_edges: dict[int, list[tuple[int, int]]],
        group_color_map: dict[int, str],
        group_element_count: dict[str, int],
        normal_flip_count: dict[int, int] | None = None,
    ) -> None:
        if self._vtk is None or self._renderer is None or self._render_window is None:
            return
        vtk = self._vtk
        window_w, window_h = self._render_window.GetSize()
        start_x = max(12, window_w - 260)
        start_y = max(40, window_h - 26)

        header = vtk.vtkTextActor()
        header.SetInput("Physical Groups")
        header_prop = header.GetTextProperty()
        header_prop.SetFontSize(14)
        header_prop.SetBold(True)
        header_prop.SetColor(0.84, 0.90, 0.97)
        header.SetDisplayPosition(start_x, start_y)
        self._renderer.AddActor2D(header)
        self._legend_actors.append(header)

        for row, group_id in enumerate(sorted(group_edges)[:10], start=1):
            color = self._hex_to_rgb(group_color_map.get(group_id, "#37c8b4"))
            element_count = int(group_element_count.get(str(group_id), 0))
            flip_count = int((normal_flip_count or {}).get(group_id, 0))
            flip_suffix = f"  flip {flip_count}" if flip_count > 0 else ""
            item = vtk.vtkTextActor()
            item.SetInput(f"G{group_id}  edges {len(group_edges[group_id])}  elems {element_count}{flip_suffix}")
            item_prop = item.GetTextProperty()
            item_prop.SetFontSize(12)
            item_prop.SetColor(color[0], color[1], color[2])
            item.SetDisplayPosition(start_x, start_y - (row * 18))
            self._renderer.AddActor2D(item)
            self._legend_actors.append(item)

    def _build_normal_arrow_actor(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        color: tuple[float, float, float],
        *,
        arrow_scale: float,
    ) -> object | None:
        if self._vtk is None:
            return None
        vtk = self._vtk
        dx, dy, dz = float(direction[0]), float(direction[1]), float(direction[2])
        dn = (dx * dx + dy * dy + dz * dz) ** 0.5
        if dn <= 1.0e-18:
            return None
        dx, dy, dz = dx / dn, dy / dn, dz / dn

        vtk_points = vtk.vtkPoints()
        vtk_normals = vtk.vtkFloatArray()
        vtk_normals.SetNumberOfComponents(3)
        vtk_normals.SetName("Normals")
        vtk_points.InsertNextPoint(float(origin[0]), float(origin[1]), float(origin[2]))
        vtk_normals.InsertNextTuple3(dx, dy, dz)

        poly = vtk.vtkPolyData()
        poly.SetPoints(vtk_points)
        poly.GetPointData().SetVectors(vtk_normals)

        arrow = vtk.vtkArrowSource()
        arrow.SetTipResolution(12)
        arrow.SetShaftResolution(10)
        glyph = vtk.vtkGlyph3D()
        glyph.SetInputData(poly)
        glyph.SetSourceConnection(arrow.GetOutputPort())
        glyph.SetVectorModeToUseVector()
        glyph.SetScaleModeToDataScalingOff()
        glyph.SetScaleFactor(float(arrow_scale))
        glyph.OrientOn()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(glyph.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(color[0], color[1], color[2])
        actor.GetProperty().SetOpacity(0.92)
        return actor

    def _group_normal_diagnostics(
        self,
        points: dict[int, tuple[float, float, float]],
        triangles: list[tuple[int, int, int]],
    ) -> dict[str, object] | None:
        if not triangles:
            return None
        normals: list[tuple[float, float, float]] = []
        centroids: list[tuple[float, float, float]] = []
        for a, b, c in triangles:
            pa = points.get(int(a))
            pb = points.get(int(b))
            pc = points.get(int(c))
            if pa is None or pb is None or pc is None:
                continue
            vax = float(pb[0]) - float(pa[0])
            vay = float(pb[1]) - float(pa[1])
            vaz = float(pb[2]) - float(pa[2])
            vbx = float(pc[0]) - float(pa[0])
            vby = float(pc[1]) - float(pa[1])
            vbz = float(pc[2]) - float(pa[2])
            nx = (vay * vbz) - (vaz * vby)
            ny = (vaz * vbx) - (vax * vbz)
            nz = (vax * vby) - (vay * vbx)
            norm = (nx * nx + ny * ny + nz * nz) ** 0.5
            if norm <= 1.0e-18:
                continue
            normals.append((nx / norm, ny / norm, nz / norm))
            centroids.append(
                (
                    (float(pa[0]) + float(pb[0]) + float(pc[0])) / 3.0,
                    (float(pa[1]) + float(pb[1]) + float(pc[1])) / 3.0,
                    (float(pa[2]) + float(pb[2]) + float(pc[2])) / 3.0,
                )
            )
        if not normals:
            return None

        mean_x = sum(n[0] for n in normals) / len(normals)
        mean_y = sum(n[1] for n in normals) / len(normals)
        mean_z = sum(n[2] for n in normals) / len(normals)
        mean_norm = (mean_x * mean_x + mean_y * mean_y + mean_z * mean_z) ** 0.5
        if mean_norm <= 1.0e-10:
            ref = normals[0]
        else:
            ref = (mean_x / mean_norm, mean_y / mean_norm, mean_z / mean_norm)

        representative_origin = (
            sum(c[0] for c in centroids) / len(centroids),
            sum(c[1] for c in centroids) / len(centroids),
            sum(c[2] for c in centroids) / len(centroids),
        )
        reversed_indices = [
            idx
            for idx, normal in enumerate(normals)
            if ((normal[0] * ref[0]) + (normal[1] * ref[1]) + (normal[2] * ref[2])) < -0.15
        ]
        reversed_count = len(reversed_indices)

        reversed_origin = None
        if reversed_count > 0:
            rx = sum(centroids[idx][0] for idx in reversed_indices) / reversed_count
            ry = sum(centroids[idx][1] for idx in reversed_indices) / reversed_count
            rz = sum(centroids[idx][2] for idx in reversed_indices) / reversed_count
            reversed_origin = (rx, ry, rz)

        return {
            "representative_origin": representative_origin,
            "representative_normal": ref,
            "reversed_count": reversed_count,
            "reversed_origin": reversed_origin,
            "triangle_count": len(normals),
        }

    def set_geometry(
        self,
        data: dict[str, object],
        *,
        group_color_map: dict[int, str],
        fallback_color: str,
        show_group_normals: bool = False,
    ) -> None:
        if not self.available or self._renderer is None or self._render_window is None:
            return
        points = dict(data.get("points", {}))
        edges = list(data.get("edges", []))
        group_edges = {
            int(group_id): list(group_data)
            for group_id, group_data in dict(data.get("group_edges", {})).items()
        }
        group_triangles = {
            int(group_id): list(group_data)
            for group_id, group_data in dict(data.get("group_triangles", {})).items()
        }
        group_element_count = {
            str(group_id): int(value)
            for group_id, value in dict(data.get("group_element_count", {})).items()
        }

        self._clear_line_actors()
        added = 0
        marker_radius = 0.0005
        normal_scale = 0.0025
        if points:
            xs = [coords[0] for coords in points.values()]
            ys = [coords[1] for coords in points.values()]
            zs = [coords[2] for coords in points.values()]
            span_x = max(xs) - min(xs)
            span_y = max(ys) - min(ys)
            span_z = max(zs) - min(zs)
            diagonal = max((span_x**2 + span_y**2 + span_z**2) ** 0.5, 1.0e-6)
            marker_radius = max(diagonal * 0.0075, 1.0e-4)
            normal_scale = max(diagonal * 0.04, 6.0e-4)

        if group_edges:
            normal_flip_count: dict[int, int] = {}
            for group_id in sorted(group_edges):
                color = self._hex_to_rgb(group_color_map.get(group_id, fallback_color))
                actor = self._build_polyline_actor(points, group_edges[group_id], color)
                if actor is not None:
                    self._renderer.AddActor(actor)
                    self._line_actors.append(actor)
                    added += 1
                centroid = self._group_centroid(points, group_edges[group_id])
                if centroid is not None:
                    self._add_group_marker(group_id, centroid, color, marker_radius)
                if show_group_normals:
                    diagnostics = self._group_normal_diagnostics(points, group_triangles.get(group_id, []))
                    if diagnostics is not None:
                        rep_actor = self._build_normal_arrow_actor(
                            diagnostics["representative_origin"],
                            diagnostics["representative_normal"],
                            color,
                            arrow_scale=normal_scale,
                        )
                        if rep_actor is not None:
                            self._renderer.AddActor(rep_actor)
                            self._normal_actors.append(rep_actor)

                        reversed_count = int(diagnostics["reversed_count"])
                        normal_flip_count[group_id] = reversed_count
                        if reversed_count > 0 and diagnostics["reversed_origin"] is not None:
                            warn_actor = self._build_normal_arrow_actor(
                                diagnostics["reversed_origin"],
                                (
                                    -float(diagnostics["representative_normal"][0]),
                                    -float(diagnostics["representative_normal"][1]),
                                    -float(diagnostics["representative_normal"][2]),
                                ),
                                (0.95, 0.22, 0.22),
                                arrow_scale=normal_scale * 0.85,
                            )
                            if warn_actor is not None:
                                self._renderer.AddActor(warn_actor)
                                self._normal_actors.append(warn_actor)
            self._add_group_legend(group_edges, group_color_map, group_element_count, normal_flip_count)
        else:
            actor = self._build_polyline_actor(points, edges, self._hex_to_rgb(fallback_color))
            if actor is not None:
                self._renderer.AddActor(actor)
                self._line_actors.append(actor)
                added += 1

        if self._text_actor is not None:
            if added > 0:
                if group_edges:
                    normal_tag = " | normals on" if show_group_normals else ""
                    self._text_actor.SetInput(f"OpenGL preview | groups {len(group_edges)}{normal_tag}")
                else:
                    self._text_actor.SetInput("OpenGL preview | no physical group tags")
            else:
                self._text_actor.SetInput("No drawable geometry")

        if added > 0:
            self._renderer.ResetCamera()
        self._render_window.Render()
