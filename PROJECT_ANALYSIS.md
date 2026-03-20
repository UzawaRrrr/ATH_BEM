# ATH Config GUI & BEM Solver - Comprehensive Project Analysis

## Executive Summary

**ATH (Acoustic Horns and Waveguides)** is a comprehensive acoustic design and simulation platform that combines a graphical configuration tool with a Boundary Element Method (BEM) solver. It enables acoustic engineers to design, visualize, and simulate acoustic horn structures and waveguide systems, then analyze their acoustic properties through frequency response and directional radiation patterns.

### Core Problem Solved
- **Acoustic Horn & Waveguide Design**: Provides tools to design and optimize acoustic horns and waveguides (common in loudspeaker systems, audio transducers, etc.)
- **Acoustic Simulation**: Simulates acoustic pressure fields around horn structures using BEM, computing frequency response and directional characteristics
- **Rapid Prototyping**: Enables fast iteration between design, preview, and simulation without leaving the application
- **Complex Boundary Condition Handling**: Supports multiple boundary conditions (source groups, rigid walls, interfaces), directional sources, and symmetry-based optimization

---

## Project Structure & Architecture

### Directory Organization

```
ath-2025-06/
├── ath_config_gui.py           # Main entry point - launches GUI
├── run_ath_gui.bat             # Windows batch launcher
├── ath_gui/                    # Multi-layered GUI application
│   ├── app.py                  # Main Tkinter window and composition root
│   ├── domain/                 # Business logic and data structures
│   │   ├── specs.py            # Application-wide constants and themes
│   │   ├── bem_specs.py        # BEM-specific field definitions
│   │   ├── config_core.py      # Configuration parsing and rendering
│   │   └── auto_enclosure.py   # Automatic enclosure geometry derivation
│   ├── infrastructure/         # External integrations and I/O
│   │   ├── bem_bridge.py       # Windows-to-WSL bridge for BEM solver
│   │   ├── bem_mesh.py         # Mesh file detection and I/O
│   │   ├── bem_results.py      # Result parsing and storage
│   │   ├── bem_state.py        # BEM state management
│   │   └── preview_core.py     # Preview geometry preparation
│   ├── presentation/           # UI components and rendering
│   │   ├── bem_plot.py         # SPL and result visualization
│   │   ├── opengl_preview.py   # OpenGL/VTK 3D preview host
│   │   ├── preview_renderer.py # Mesh and geometry rendering
│   │   └── widgets.py          # Custom Tkinter widgets
│   ├── application/            # Workflow orchestration
│   │   └── controllers/        # Use-case controllers
│   │       ├── workflow_controller.py
│   │       ├── bem_controller.py
│   │       └── preview_controller.py
│   ├── tools/                  # Development utilities
│   │   └── check_layering.py   # Validates architectural layers
│   └── LAYER_CONTRACT.md       # Architectural enforcement rules
│
├── bem_solver/                 # External BEM solver (Python CLI)
│   ├── solver_cli.py           # CLI entry point for BEM computation
│   ├── solver_core.py          # Core Helmholtz equation solver (bempp-cl)
│   ├── job_model.py            # BEM job schema and validation
│   ├── mesh_adapter.py         # Mesh preparation and boundary roles
│   ├── postprocess.py          # SPL calculation, polar diagram generation
│   ├── export_results.py       # Result serialization (NPZ, CSV, PNG)
│   ├── symmetry.py             # Symmetry configuration and transforms
│   ├── symmetry_mesh.py        # Symmetry-aware mesh reduction
│   └── job.example.json        # Example BEM job configuration
│
├── ath_config_gui.py           # Backward compatibility shim
├── tests/                      # Unit and smoke tests
│   ├── test_symmetry_mesh_orientation.py
│   └── test_symmetry_source_rebuild.py
└── doc/                        # Documentation and example configs
    ├── Autima_1.cfg, 1_5, 1_75, 1_8.cfg
    └── test.cfg
```

### Layered Architecture Enforcement

The project implements a **strict 5-layer architecture** to maintain separation of concerns:

| Layer | Purpose | Can Depend On | Example |
|-------|---------|---------------|---------|
| **Domain** | Pure business logic, data structures, no I/O | `domain` ← `domain` | `specs.py`, `config_core.py`, `bem_specs.py` |
| **Infrastructure** | External adapters, file I/O, external tools | `domain`, `infrastructure` | `bem_bridge.py`, `bem_mesh.py`, mesh file reading |
| **Presentation** | UI components, rendering, user interaction | `domain`, `presentation` | Tkinter widgets, OpenGL preview, plot rendering |
| **Application** | Workflow orchestration, use-case coordination | All layers | Controllers that combine domain + infra + presentation |
| **Composition Root** | App initialization and DI (in `app.py`) | All layers | Main window setup, controller instantiation |

**Architectural Guardrail**: Run `python ath_config_gui.py --check-layering` to detect dependency violations.

---

## Main Components & Responsibilities

### 1. Entry Points

#### `ath_config_gui.py`
- Simple bootstrapper that imports and calls `main()` from `ath_gui.app`
- Allows `raise SystemExit` pattern for clean process exit
- Supports command-line arguments: `--self-test`, `--check-layering`

#### `run_ath_gui.bat`
- Windows batch script for convenient GUI launch
- Sets working directory and invokes Python entry point

#### `ath_gui/app.py` → `AthConfigStudio(tk.Tk)`
- Main Tkinter window class (composition root)
- Creates and manages GUI tabs:
  - **Config Tab**: Edit horn configuration parameters
  - **Preview Tab**: Real-time 3D geometry visualization (OpenGL)
  - **BEM Tab**: Configure solver parameters and view results
  - **Status Bar**: Process status and logging
- Maintains internal state for current configuration and BEM jobs
- Orchestrates controller interactions

### 2. Domain Layer (Pure Business Logic)

#### `domain/specs.py`
- Application-wide constants: window title, color scheme (dark theme), dimensions
- Default configuration structures
- Theme definitions (accent colors, backgrounds, borders)

#### `domain/config_core.py`
- **Configuration Schema**: Defines configuration file structure
- **Parsing**: Reads `.cfg` files into structured data
- **Rendering**: Converts structured data back to `.cfg` text format (preserving comments)
- **Validation**: Checks field types and value constraints
- **Field Hints**: Provides tooltip descriptions for all parameters
- Uses a `FieldSection` concept to organize parameters into logical groups

#### `domain/bem_specs.py`
- Defines all BEM-specific GUI fields:
  - **Mesh Fields**: Mesh file path, scale factor, surface groups
  - **Solver Fields**: Frequency range (200-20000 Hz, 48 points log-spaced), velocity model
  - **Symmetry Fields**: X/Y symmetry planes, even/odd parity options
  - **Observation Fields**: Microphone distance, measurement plane (XZ or YZ), angle range
- Maps UI form fields to BEM job parameters

#### `domain/auto_enclosure.py`
- Derives automatic enclosure geometry based on horn profile and external parameters
- Handles edge cases where user wants automatic boundary generation

### 3. Infrastructure Layer (External Integrations)

#### `infrastructure/bem_bridge.py` ⟷ WSL/BEM Solver
- **Purpose**: Bridge Windows GUI ↔ WSL (Windows Subsystem for Linux) BEM solver
- **Key Functions**:
  - `windows_path_to_wsl()`: Converts Windows paths to WSL paths (e.g., `C:\path` → `/mnt/c/path`)
  - `build_bem_solver_command()`: Constructs bash command to launch BEM solver in WSL with proper virtual environment
  - `expand_wsl_user_path()`: Resolves `~/` paths to `${HOME}/` for bash expansion
  - Handles subprocess management and log streaming

#### `infrastructure/bem_mesh.py`
- **Mesh Detection**: Scans output directories for latest `.msh` files (Gmsh format)
- **Group Analysis**: Reads mesh group information from Gmsh physical tags
- **Mesh Info**: Collects statistics (vertex count, element count, surface area, bbox)
- **Boundary Role Detection**: Analyzes which geometry surface groups are closed manifolds vs. open boundaries

#### `infrastructure/bem_results.py`
- Loads BEM solver outputs:
  - `solution.npz`: NumPy compressed archive with complex pressure field
  - `summary.json`: Solver metadata and diagnostics
  - `mesh_info.json`: Mesh statistics
  - `polar.csv`: Frequency vs. angle SPL data
  - `polar.png`: Pre-rendered directional polar diagrams
- Provides dictionary-like access to results for UI display

#### `infrastructure/bem_state.py`
- Maintains BEM simulation state (last job, current results, ready status)
- Tracks configuration changes and invalidates results when needed

#### `infrastructure/preview_core.py`
- **Output Directory Resolution**: Computes where to search for generated geometry
- **Mesh File Discovery**: Locates `.msh`, `.geo`, `.stl` files in output directories
- **Search Prioritization**: Finds most recently generated files across multiple project folders
- **Group Source Annotation**: Describes which tool generated the mesh (ATH simulation, gmsh, etc.)

### 4. Presentation Layer (UI Components)

#### `presentation/widgets.py`
- **ScrollableFrame**: Custom Tkinter widget for scrollable form fields
- **DynamicForm**: Builds forms from field specifications
- **FileSelectButton**: Browse button for file selection

#### `presentation/opengl_preview.py`
- **OpenGL Host Container**: Wraps VTK rendering context for Tkinter
- **VTK Interactor**: Handles mouse rotation, zoom, pan of 3D mesh
- **Probe Detection**: Checks if VTK library is available; falls back to placeholder if not

#### `presentation/preview_renderer.py`
- **Mesh Rendering**: Converts triangle mesh data to VTK format
- **Group Coloring**: Colors different surface groups distinctly
- **Geometry Visualization**: Handles edge cases (empty data, single vertex, etc.)
- **Zoom-to-fit**: Auto-adjusts camera to frame geometry

#### `presentation/bem_plot.py`
- **SPL Visualization**: Plots frequency response (magnitude vs. frequency)
- **Polar Diagrams**: Renders polar plots of directional radiation
- **Matplotlib Integration**: Uses matplotlib for plotting, stores figures as Tkinter-compatible images
- **Fallback Diagrams**: Shows placeholder if data unavailable

### 5. Application Layer (Workflow Orchestration)

#### `application/controllers/workflow_controller.py`
- Orchestrates multi-step workflows:
  1. Load configuration file
  2. Parse and validate parameters
  3. Generate preview geometry
  4. Setup BEM job
  5. Launch solver
  6. Monitor progress
  7. Load and display results

#### `application/controllers/bem_controller.py`
- **Job Submission**: Takes user-configured parameters, creates BEM job JSON
- **WSL Bridge**: Invokes `bem_bridge.py` to launch solver with proper environment
- **Progress Tracking**: Monitors subprocess output and updates UI status
- **Error Handling**: Collects warnings/errors from solver, displays to user

#### `application/controllers/preview_controller.py`
- **Geometry Loading**: Converts `.msh`/`.geo`/`.stl` files to 3D displayable format
- **Group Management**: Manages which groups are visible/hidden
- **Render Updates**: Pushes geometry changes to OpenGL renderer

---

## BEM Solver Architecture (`bem_solver/` subdirectory)

### Problem: Acoustic Radiation Simulation

The BEM solver computes acoustic pressure fields around horn structures by solving the **exterior Helmholtz equation** with boundary conditions.

$$\nabla^2 p + k^2 p = 0 \quad \text{(in free space)}$$

where $k = \omega/c$ is the wavenumber.

### Workflow

```
job.json (user config)
    ↓
solver_cli.py (entry point)
    ↓
job_model.py (parse & validate)
    ↓
mesh_adapter.py (load mesh, identify boundary roles)
    ↓
symmetry.py (optional: reduce mesh via plane symmetries)
    ↓
solver_core.py (solve Helmholtz with bempp-cl)
    ↓
postprocess.py (compute SPL, polar diagrams)
    ↓
export_results.py (save .npz, .csv, .png)
```

### Key Modules

#### `job_model.py` — BEM Job Schema
- **`BemJob` dataclass**: Complete configuration for one BEM run
  - Mesh file & scaling
  - Surface group roles (source, wall, interface, ignore)
  - Source parameters: gain, direction vectors, velocity model
  - Frequency range: $f_1$ to $f_2$, log or linear spacing
  - Observation setup: microphone distance, measurement plane, angle range
  - Symmetry configuration
  - Output options (PNG export, boundary pressure export)
- **Validation**: Ensures all required fields present, sensible numeric ranges

#### `mesh_adapter.py` — Mesh Loading & Analysis
- **Mesh I/O**: Reads Gmsh `.msh` files using `meshio` library
- **Group Identification**: Extracts surface group IDs from Gmsh physical tags
- **Manifold Analysis**: Detects closed surfaces (rigid walls) vs. open boundaries
- **Role Resolution**: Classifies groups as:
  - **Source Groups**: Vibrating surfaces with prescribed velocity
  - **Wall Groups**: Rigid, non-vibrating boundaries
  - **Interface Groups**: (Reserved for future multi-domain support)
  - **Ignore Groups**: Excluded from computation
- **Surface Area / Element Count**: Computes statistics per group
- **Data Output**: `MeshInfo` structure with diagnostics

#### `solver_core.py` — Core BEM Computation

**Libraries**: `bempp_cl` (Boundary Element Method in Python with OpenCL acceleration)

**Solver Strategy**: Exterior Helmholtz equation with:
- **Velocity Boundary Condition (BC)**: Prescribed normal velocity on sources
- **Rigid Wall BC**: Zero normal velocity (Neumann condition)
- **GMRES Solver**: Iterative linear solver with configurable tolerance
- **Frequency Sweep**: Solves at each frequency independently (200 Hz to 20 kHz)

**Key Functions**:
- `_build_velocity_coefficients()`: Converts user source gain & direction to element-wise velocity BC
- `_direction_correction()`: Applies directional filtering (source points in specific direction)
- `_solve_linear_system()`: Wraps `scipy.sparse.linalg.gmres()` with convergence tracking
- `compute_velocity_frequency_weighting()`: Applies frequency-dependent source weighting (e.g., `inverse_jw` mode for velocity sources)

**Output**: `SolverResult(frequencies_hz, angles_deg, pressure_complex, spl_db, warnings, notes)`

#### `postprocess.py` — Results Analysis
- **Frequency Axis**: Generates log or linear frequency spacing
- **Observation Points**: Creates microphone array at specified distance and angles
- **Pressure → SPL Conversion**: 
  $$\text{SPL} = 20 \log_{10}\left(\frac{|p|}{p_{\text{ref}}}\right)$$
  where $p_{\text{ref}} = 20 \mu\text{Pa}$ (reference pressure)
- **Polar Diagram Rendering**: Matplotlib-based heatmap of SPL vs. frequency & angle (Klippel-like color scale)
- **Export to PNG**: High-resolution polar diagram image for documentation

#### `export_results.py` — Serialization
- **`.npz` Format**: NumPy compressed archive (pressure field, frequency/angle arrays)
- **`.csv` Format**: Tabular polar data (frequency, angle, SPL)
- **`mesh_info.json`**: Mesh statistics and group information
- **`summary.json`**: Solver diagnostics, runtime, warnings
- **`polar.png`**: Pre-rendered directional plots

#### `symmetry.py` — Symmetry Reduction
- **Purpose**: Exploit geometric symmetries to reduce computational cost dramatically (2-4× speedup)
- **Supported Modes**:
  - `off`: No symmetry (full mesh computation)
  - `half_x_even`: Mirror symmetry about X plane (even parity)
  - `half_y_even`: Mirror symmetry about Y plane (even parity)
  - `quarter_xy_even_even`: Two plane symmetries (XY quarter space)
- **Image Transforms**: Each mirror creates virtual "image" sources and walls; solution reconstructed via superposition
- **Plane Definition**: Specify axis (x/y/z), plane position, parity (even/odd)
- **Validation**: Checks that mesh is symmetric to specified tolerance

#### `symmetry_mesh.py` — Mesh Reduction
- **Submesh Extraction**: Keeps only portion of mesh in fundamental domain
- **Manifold Validation**: Ensures reduced mesh forms valid closed/open boundary manifold
- **Mirrored Mesh Rebuild**: Reconstructs full-domain solution from reduced-domain result
- **Debug Output**: Optional full-mesh rebuild for verification

---

## Configuration System

### File Format: `.cfg` (Text Config)

```ini
; Generated by ATH Config Studio

[Global]
OutputRootDir = "E:/pythonGATH"
MeshCmd = "E:\pythonGATH\.venv\Scripts\python.exe gmsh %f -"
GnuplotPath = "C:\Program Files\gnuplot\bin\gnuplot"

[Horn.Profile]
Type = "Exponential"
Throat.Diameter = 0.05
Throat.Length = 0.1
Mouth.Diameter = 0.3
Mouth.Length = 0.2
Flare.Rate = 1.5
...

[Horn.Boundary]
...

[BEM]
MeshFile = "output/horn.msh"
SourceGroups = "1001"
WallGroups = "1,2,3"
F1 = 200.0
F2 = 20000.0
NumFreq = 48
...
```

### Example Configurations
Located in `doc/`:
- `Autima_1.cfg`, `Autima_1_5.cfg`, `Autima_1_75.cfg`, `Autima_1_8.cfg`: Horn family variations
- `test.cfg`: Simple test configuration

### BEM Job Schema (JSON)
Located in `bem_solver/job.example.json` — Configuration passed to solver CLI:

```json
{
  "mesh_file": "C:/path/to/horn.msh",
  "mesh_scale_to_meter": 0.001,
  "solver_mode": "exterior_velocity_bc",
  "source_groups": [1001],
  "wall_groups": [1, 2, 3],
  "source_gain": [1.0],
  "source_direction": [[0.0, 0.0, 1.0]],
  "f1": 200.0,
  "f2": 20000.0,
  "num_freq": 48,
  "frequency_spacing": "log",
  "symmetry": {
    "enabled": false,
    "planes": []
  }
}
```

---

## Key Workflows

### Workflow 1: Load & Design
```
User opens GUI
    ↓
Load existing .cfg file (or create new) → domain/config_core.py parses
    ↓
GUI form populated with parameters (domain/bem_specs.py)
    ↓
User edits horn profile, boundary conditions, mesh settings
```

### Workflow 2: Preview & Visualize
```
User clicks "Generate Preview"
    ↓
infrastructure/preview_core.py finds latest .msh file
    ↓
infrastructure/bem_mesh.py loads mesh groups and analysis
    ↓
presentation/preview_renderer.py converts to VTK geometry
    ↓
OpenGL preview window displays 3D radiometric render
```

### Workflow 3: Configure & Simulate
```
User configures BEM parameters (frequency, sources, walls, symmetry)
    ↓
application/bem_controller.py creates job.json
    ↓
infrastructure/bem_bridge.py constructs WSL command
    ↓
bem_solver/solver_cli.py loads job.json & mesh
    ↓
bem_solver/mesh_adapter.py identifies boundary roles
    ↓
bem_solver/symmetry.py optionally reduces mesh
    ↓
bem_solver/solver_core.py solves Helmholtz at each frequency (bempp-cl)
    ↓
bem_solver/postprocess.py computes SPL & polar diagrams
    ↓
bem_solver/export_results.py saves .npz, .csv, .png
    ↓
GUI loads results (infrastructure/bem_results.py)
    ↓
presentation/bem_plot.py displays SPL response & polar radiation pattern
```

### Workflow 4: Symmetry Optimization (Optional)
```
User selects symmetry mode (e.g., "half_x_even")
    ↓
bem_solver/symmetry.py defines mirror planes & image transforms
    ↓
bem_solver/symmetry_mesh.py extracts submesh in fundamental domain
    ↓
solver_core.py solves on reduced mesh (2-4× faster)
    ↓
Results reconstructed via superposition of real + image sources
```

---

## Technology Stack

### Frontend & GUI
| Component | Library | Purpose |
|-----------|---------|---------|
| **Window Framework** | `tkinter` | Cross-platform GUI toolkit (Python standard) |
| **UI Theme** | Custom dark theme | Custom colors (accent, backgrounds, borders) |
| **3D Visualization** | `VTK` (Visualization Toolkit) | 3D mesh rendering, OpenGL interactor |
| **Form Widgets** | Custom (`presentation/widgets.py`) | Dynamic forms, file browsing |
| **Plot/Diagram** | `matplotlib` | 2D SPL plots, polar (heatmap) diagrams |

### Backend & Numerical Computation
| Component | Library | Purpose |
|-----------|---------|---------|
| **BEM Solver** | `bempp-cl` | Boundary Element Method with OpenCL acceleration |
| **Mesh I/O** | `meshio` | Read/write Gmsh `.msh`, `.geo`, `.stl` files |
| **Numerical Core** | `numpy`, `scipy` | Linear algebra, sparse matrices, GMRES solver |
| **Mesh Generation** | `gmsh` (external) | Generate computational meshes from geometry |
| **Data Serialization** | `numpy.savez`, `json` | Store/load numerical results and configs |

### System Integration
| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Process Management** | `subprocess`, `shlex` | Launch external solver, manage pipes |
| **WSL Bridge** | Windows ↔ WSL path conversion | Run Linux-only BEM solver from Windows GUI |
| **File I/O** | `pathlib.Path`, `json`, `configparser` | Configuration and result file handling |
| **Logging** | `sys.stdout` streams | Real-time progress/error reporting |

### Development & Testing
| Component | Library | Purpose |
|-----------|---------|---------|
| **Package Management** | `pip`, `venv` | Virtual environments for isolation |
| **Type Hints** | `from __future__ import annotations` | Code clarity and IDE support |
| **Testing** | Custom `self_test.py` | Smoke tests and layer validation |
| **Validation** | `tools/check_layering.py` | Architectural dependency enforcement |

---

## External Dependencies

### Critical Dependencies (Must Install)
```
bempp-cl              # BEM solver core (GPU-accelerated via OpenCL)
meshio                # Mesh file I/O
numpy                 # Numerical arrays
scipy                 # Advanced math (GMRES, sparse linalg)
matplotlib            # Plotting

Optional (for visualization):
VTK                   # 3D rendering
pyopencl              # (included with bempp-cl, GPU acceleration)
```

### System Requirements
- **Python 3.9+** (or latest compatible with bempp-cl)
- **Windows 10+** with WSL/WSL2 (for BEM solver execution)
- **OpenCL-capable GPU** or **multi-core CPU** (bempp-cl can use either)
- **gmsh** executable (for mesh generation)
- **Gnuplot** (optional, for advanced plotting)

### Virtual Environment Setup
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# WSL (for BEM solver)
python -m venv ~/venvs/bempp-wsl
source ~/venvs/bempp-wsl/bin/activate
pip install bempp-cl numpy scipy meshio matplotlib
```

---

## Data Flow: End-to-End Example

**Scenario**: User designs an exponential horn, configures 200-20k Hz analysis, and simulates acoustic response.

```
1. USER ACTION: Load "Autima_1.cfg"
   → domain/config_core.py parses INI structure
   → Populates AthConfigStudio form fields

2. USER ACTION: Edit horn profile (mouth diameter, flare rate)
   → presentation/widgets.py captures form changes
   → domain state updated in background

3. USER ACTION: Click "Generate Preview"
   → User's current config exported as temporary geometry
   → infrastructure/bem_mesh.py locates latest .msh file
   → presentation/preview_renderer.py loads mesh
   → OpenGL window renders 3D horn shape with colored surface groups

4. USER ACTION: Configure BEM (F1=200Hz, F2=20kHz, 48 points, symmetry=half_x)
   → domain/bem_specs.py validates frequency range
   → application/bem_controller.py builds job.json

5. USER ACTION: Click "Run BEM Solver"
   → infrastructure/bem_bridge.py converts paths to WSL format
   → subprocess launches: wsl python ~/bem_solver/solver_cli.py ~/bem_solver/job.json
   
6. IN WSL (bem_solver/):
   a. solver_cli.py loads job.json
   b. mesh_adapter.py reads horn.msh, identifies source & wall groups
   c. symmetry.py reduces mesh to half domain (applies even-X mirror)
   d. symmetry_mesh.py extracts submesh, validates manifold
   e. solver_core.py:
      - For f = [200, 250.5, ..., 20000] Hz:
        - Build Helmholtz integral equation matrix (bempp-cl)
        - Apply velocity BC on source groups
        - Apply Neumann BC on wall groups
        - Solve via GMRES: LHS @ x = RHS
        - Evaluate pressure at 361 observation points (full circle, 5m distance)
        - Convert to SPL (dB re 20 μPa)
   f. postprocess.py generates 2D SPL(freq, angle) matrix
   g. export_polar_png() creates frequency-angle heatmap
   h. export_results.py saves: solution.npz, polar.csv, polar.png, summary.json

7. RESULT LOADING (back in GUI):
   → infrastructure/bem_results.py loads summary.json, polar.csv, polar.png
   → application/bem_controller.py updates UI
   → presentation/bem_plot.py displays:
     - SPL vs Frequency curve (on-axis response)
     - Polar radiation heatmap (directional response)
   → User reviews frequency response (50 dB @ 250 Hz, slight dip at 5 kHz, etc.)
   → Iterates design if needed
```

---

## Testing & Quality Assurance

### Self-Test Suite
```bash
python ath_config_gui.py --self-test
```
Includes:
- Configuration parsing/rendering round-trip tests
- Layer architecture validation (no illegal cross-layer imports)
- Mesh detection and group analysis
- Symmetry configuration parsing
- WSL path conversion correctness

### Unit Tests
Located in `tests/`:
- `test_symmetry_mesh_orientation.py`: Validates mesh reduction under symmetry
- `test_symmetry_source_rebuild.py`: Confirms image source generation

### Smoke Tests
- Launch GUI with sample config → check window appears
- Generate preview → confirm mesh loads
- Submit minimal BEM job → check solver runs without errors

---

## Development Practices & Constraints

### Architectural Rules (Enforced)
1. **Domain Layer Isolation**: `domain/` modules contain zero I/O or UI logic
2. **Infrastructure Adapters**: All external integrations (files, subprocesses, libraries) isolated in `infrastructure/`
3. **Presentation Independence**: `presentation/` modules assume abstract data; no business logic
4. **Application Orchestration**: `application/` wires layers together; never skips layers
5. **Composition Root**: `app.py` is the only place DI and module imports happen

### Chinese Localization
- All UI strings, labels, tooltips in Traditional Chinese (繁體中文)
- Configuration file comments preserved in Chinese
- Supports Chinese fonts (Microsoft JhengHei, Noto Sans CJK)

### Cross-Platform Considerations
- **Windows-first GUI** (Tkinter, VTK rendering)
- **WSL2 BEM Solver** (Linux-based bempp-cl is more stable)
- Path conversion Windows ↔ WSL handled automatically
- Batch script (`run_ath_gui.bat`) for end-user convenience

---

## Known Limitations & Future Extensions

### Current Scope
- ✅ Exterior Helmholtz (free-space radiation)
- ✅ Velocity boundary conditions (normal surface velocity)
- ✅ Rigid wall boundary conditions (Neumann: zero velocity)
- ✅ Single-frequency-per-run (frequency sweep in loop)
- ✅ Cartesian symmetry reduction (X, Y, XY planes)
- ✅ 360° polar observation

### Not Yet Implemented
- ❌ Interior domains (enclosed cavities)
- ❌ Impedance boundary conditions (complex absorptive walls)
- ❌ Fluid-structure coupling
- ❌ Multi-threaded frequency parallelization
- ❌ GPU-only acceleration mode (currently OpenCL optional)
- ❌ 3D farfield acoustic imaging

### Extensibility Points
- **New Solver Modes**: Add to `bem_solver/solver_core.py` (interior, impedance, etc.)
- **New Symmetry Types**: Extend `bem_solver/symmetry.py` (cylindrical, etc.)
- **Custom Visualization**: Subclass `presentation/preview_renderer.py`
- **Alternative Mesh Generators**: Adapt `infrastructure/bem_mesh.py` to support other formats
- **Optimization Tools**: Add to `application/controllers/` (parameter sweep, sensitivity analysis)

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Purpose** | Acoustic horn/waveguide design, visualization, and BEM acoustic simulation |
| **Architecture** | 5-layer (domain, infrastructure, presentation, application, composition) |
| **Frontend** | Python Tkinter GUI with Chinese localization, VTK 3D preview, matplotlib plots |
| **Solver** | bempp-cl (BEM) with symmetry-based acceleration, 200Hz–20kHz frequency sweep |
| **Mesh** | Gmsh `.msh` files; group-based boundary role assignment |
| **Results** | SPL response, polar radiation diagrams, frequency-dependent directivity |
| **Config** | Text-based `.cfg` format; JSON schema for BEM jobs |
| **Integration** | Windows GUI ↔ WSL2 BEM solver via subprocess; automatic path conversion |
| **Testing** | Self-tests, layer validation, smoke tests for workflows |
| **Tech Stack** | Python 3, Tkinter, bempp-cl, numpy, scipy, matplotlib, meshio, VTK |
| **Deployment** | Portable `.venv` on Windows; separate WSL environment for solver |

---

## How to Extend or Contribute

1. **Add New BEM Feature**: Modify `bem_solver/solver_core.py` and add tests to `tests/`
2. **Enhance GUI**: Use `create_and_run_task` to add controller in `application/controllers/`, expose via `app.py`
3. **New Configuration Parameter**: Add to `domain/configs.py` and corresponding `domain/bem_specs.py` field
4. **Fix Architecture Violation**: Run `--check-layering` and move imports/code to correct layer
5. **Add Documentation**: Update `LAYER_CONTRACT.md` and `LAYER_LAYOUT.md` to reflect changes

---

*Generated: March 2026 | Version: pythonGATH / ATH GUI 中文版 2026-03-19*
