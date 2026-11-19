"""Write every result of the pipe run into one Excel workbook: results/pipe_results.xlsx

Sheets: Summary · Axial_Profiles · Radial_Profiles · Wall · Convergence · Full_Field
Run after post_pipe.py (needs flow.vtu, surface_flow.csv, history.csv, results/).
"""
import csv, json, os
import numpy as np
import pyvista as pv
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference, ScatterChart, Series
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = os.path.join("results", "pipe_results.xlsx")
F = "Arial"
H_FONT = Font(name=F, bold=True, color="FFFFFF")
H_FILL = PatternFill("solid", fgColor="1F4E78")
IN_FONT = Font(name=F, color="0000FF")          # hard-coded inputs
BODY = Font(name=F)
BOLD = Font(name=F, bold=True)
THIN = Border(bottom=Side(style="thin", color="BFBFBF"))


def header(ws, row, names, widths=None):
    for j, n in enumerate(names, 1):
        c = ws.cell(row, j, n)
        c.font, c.fill = H_FONT, H_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(j, 16)
    ws.row_dimensions[row].height = 32
    ws.freeze_panes = ws.cell(row + 1, 1)


def table(ws, row0, rows, fmt="0.000000"):
    for i, r in enumerate(rows):
        for j, v in enumerate(r, 1):
            c = ws.cell(row0 + i, j, float(v))
            c.font, c.number_format = BODY, fmt


def line_chart(ws, title, ytitle, xcol, ycols, n, anchor, row0=2):
    ch = ScatterChart()
    ch.title, ch.style, ch.height, ch.width = title, 13, 8, 16
    ch.x_axis.title, ch.y_axis.title = "x [m] (inlet → outlet)", ytitle
    xr = Reference(ws, min_col=xcol, min_row=row0, max_row=row0 + n - 1)
    for yc in ycols:
        s = Series(Reference(ws, min_col=yc, min_row=row0 - 1, max_row=row0 + n - 1), xr, title_from_data=True)
        s.marker.symbol = "none"; s.smooth = False
        ch.series.append(s)
    ch.roundedCorners = False
    ch.legend.overlay = False; ch.title.overlay = False
    ch.x_axis.title.overlay = False; ch.y_axis.title.overlay = False
    ch.x_axis.delete = False; ch.y_axis.delete = False
    ws.add_chart(ch, anchor)


# ------------------------------------------------------------------ data
m = pv.read("flow.vtu")
P = m.points[:, :2]
pd_ = {k: np.asarray(m.point_data[k]) for k in m.point_data.keys()}
U, V = pd_["Velocity"][:, 0], pd_["Velocity"][:, 1]
speed = np.hypot(U, V)
summ = json.load(open(os.path.join("results", "summary.json")))
ax = list(csv.DictReader(open(os.path.join("results", "axial_profiles.csv"))))
cfg = {}
for ln in open("pipe.cfg"):
    if "=" in ln and not ln.lstrip().startswith("%"):
        k, v = ln.split("=", 1); cfg[k.strip()] = v.strip()
p_out = float(cfg["MARKER_OUTLET"].strip("() ").split(",")[1])

wb = Workbook()

# ------------------------------------------------------------------ Summary
ws = wb.active; ws.title = "Summary"
ws["A1"] = "Straight pipe, inlet Mach 0.5 — SU2 axisymmetric RANS (Spalart–Allmaras)"; ws["A1"].font = Font(name=F, bold=True, size=14)
ws["A2"] = "Blue = input values; black = formulas; values below the inputs are CFD results from results/summary.json."
ws["A2"].font = Font(name=F, italic=True, color="595959")
ws.column_dimensions["A"].width = 34
for c in "BCDE":
    ws.column_dimensions[c].width = 18

ws["A4"] = "Case inputs"; ws["A4"].font = BOLD
inputs = [("Pipe length L [m]", 2.2, "0.00"), ("Pipe diameter D [m]", 0.5, "0.00"),
          ("Target inlet Mach", 0.5, "0.000"), ("Inlet static pressure target [Pa]", 101325, "#,##0"),
          ("Inlet static temperature [K]", 288.15, "0.00"), ("Gamma (air)", 1.4, "0.00"),
          ("Gas constant R [J/kg/K]", 287.058, "0.000"), ("Outlet static pressure (converged) [Pa]", p_out, "#,##0.0")]
for i, (k, v, f) in enumerate(inputs):
    r = 5 + i
    ws.cell(r, 1, k).font = BODY
    c = ws.cell(r, 2, v); c.font, c.number_format = IN_FONT, f
ws["B5"].comment = Comment("User request: 2.2 m long pipe", "Claude")
ws["B6"].comment = Comment("User request: 0.5 m diameter", "Claude")
ws["B7"].comment = Comment("User request: 0.5 Mach at the inlet", "Claude")
ws["B8"].comment = Comment("Assumption: ISA sea level", "Claude")
ws["B9"].comment = Comment("Assumption: ISA sea level", "Claude")
ws["B12"].comment = Comment("Found by run_pipe.py so that the inlet Mach = 0.500", "Claude")

ws["A14"] = "Derived inlet boundary conditions"; ws["A14"].font = BOLD
derived = [("Inlet total temperature T0 [K]", "=B9*(1+(B10-1)/2*B7^2)", "0.00"),
           ("Inlet total pressure p0 [Pa]", "=B8*(1+(B10-1)/2*B7^2)^(B10/(B10-1))", "#,##0.0"),
           ("Speed of sound at inlet [m/s]", "=SQRT(B10*B11*B9)", "0.00"),
           ("Target inlet velocity [m/s]", "=B7*B17", "0.00"),
           ("Pipe cross-section area [m²]", "=PI()*B6^2/4", "0.00000")]
for i, (k, f_, nf) in enumerate(derived):
    r = 15 + i
    ws.cell(r, 1, k).font = BODY
    c = ws.cell(r, 2, f_); c.font, c.number_format = BODY, nf

ws["A21"] = "Results: inlet vs outlet"; ws["A21"].font = BOLD
for j, h in enumerate(["Quantity", "Inlet (x = 0 m)", "Outlet (x = 2.2 m)", "Change", "Change [%]"], 1):
    c = ws.cell(22, j, h); c.font, c.fill = H_FONT, H_FILL; c.alignment = Alignment(horizontal="center")
rows = [("Static pressure, area-avg [Pa]", "p_static_Pa", "#,##0.0"),
        ("Static pressure, centreline [Pa]", "p_centreline_Pa", "#,##0.0"),
        ("Bulk axial velocity [m/s]", "U_bulk_m_s", "0.00"),
        ("Centreline velocity [m/s]", "U_centreline_m_s", "0.00"),
        ("Mach, mass-avg", "Mach_mass_avg", "0.0000"),
        ("Mach, centreline", "Mach_centreline", "0.0000"),
        ("Temperature, mass-avg [K]", "T_K", "0.00"),
        ("Density, area-avg [kg/m³]", "rho_kg_m3", "0.0000"),
        ("Mass flow [kg/s]", "mdot_kg_s", "0.000")]
for i, (k, key, nf) in enumerate(rows):
    r = 23 + i
    ws.cell(r, 1, k).font = BODY
    for col, side in ((2, "inlet"), (3, "outlet")):
        c = ws.cell(r, col, summ[side][key]); c.font, c.number_format = BODY, nf
    c = ws.cell(r, 4, f"=C{r}-B{r}"); c.font, c.number_format = BODY, nf
    c = ws.cell(r, 5, f"=IF(B{r}=0,0,(C{r}-B{r})/B{r})"); c.font, c.number_format = BODY, "0.00%"
    for col in range(1, 6):
        ws.cell(r, col).border = THIN

ws["A33"] = "Checks"; ws["A33"].font = BOLD
checks = [("Pressure drop Δp [Pa]", "=B23-C23", "#,##0.0"),
          ("Dynamic pressure at inlet ½ρV² [Pa]", "=0.5*B30*B25^2", "#,##0.0"),
          ("Apparent Darcy friction factor f = Δp/(L/D · ½ρV²)", "=B34/(B5/B6*B35)", "0.0000"),
          ("Reynolds number at inlet (μ from Sutherland)", "=B30*B25*B6/(1.716E-5*(B29/273.15)^1.5*(273.15+110.4)/(B29+110.4))", "#,##0"),
          ("Mass imbalance outlet vs inlet", "=E31", "0.000%"),
          ("Inlet Mach error vs target", "=B27-B7", "0.0000"),
          ("Wall y+ mean (target ≈ 1)", summ.get("wall_yplus", {}).get("mean"), "0.00"),
          ("Wall y+ max", summ.get("wall_yplus", {}).get("max"), "0.00")]
for i, (k, v, nf) in enumerate(checks):
    r = 34 + i
    ws.cell(r, 1, k).font = BODY
    c = ws.cell(r, 2, v); c.font, c.number_format = BODY, nf
ws["C36"] = "fully developed smooth pipe at this Re ≈ 0.009; higher here because the flow is still developing (L/D = 4.4)"
ws["C36"].font = Font(name=F, italic=True, color="595959")

ws["A43"] = "Method"; ws["A43"].font = BOLD
notes = ["Solver: SU2 8.1.0, compressible RANS, Spalart–Allmaras, axisymmetric (x = axis, y = radius).",
         "Mesh: 220 × 90 structured quads (Gmsh), first cell 2 µm at the wall, grows to 25 mm at the axis.",
         "Inlet: total pressure/temperature of the M 0.5 state; outlet: static pressure; wall: adiabatic no-slip; axis: symmetry.",
         "Air: ideal gas γ = 1.4, Sutherland viscosity, Pr = 0.72 (laminar) / 0.9 (turbulent).",
         "Area-avg = ∫φ·2πr dr / πR²; mass-avg weighted by ρu; bulk velocity = ṁ / (ρ̄A)."]
for i, n in enumerate(notes):
    ws.cell(44 + i, 1, n).font = BODY

# ------------------------------------------------------------------ Axial profiles
wa = wb.create_sheet("Axial_Profiles")
cols = [("x", "x [m]"), ("p_area", "Static p, area-avg [Pa]"), ("p_axis", "Static p, centreline [Pa]"),
        ("U_bulk", "Bulk velocity [m/s]"), ("U_axis", "Centreline velocity [m/s]"),
        ("M_mass", "Mach, mass-avg"), ("M_axis", "Mach, centreline"),
        ("T_mass", "Temperature, mass-avg [K]"), ("rho_area", "Density, area-avg [kg/m³]"),
        ("mdot", "Mass flow [kg/s]")]
header(wa, 1, [c[1] for c in cols])
table(wa, 2, [[r[k] for k, _ in cols] for r in ax])
n = len(ax)
line_chart(wa, "Static pressure inlet → outlet", "p [Pa]", 1, [2, 3], n, "L2")
line_chart(wa, "Axial velocity inlet → outlet", "u [m/s]", 1, [4, 5], n, "L19")
line_chart(wa, "Mach number inlet → outlet", "Mach", 1, [6, 7], n, "L36")

# ------------------------------------------------------------------ Radial profiles
wr = wb.create_sheet("Radial_Profiles")
xs = np.unique(np.round(P[:, 0], 6))
stations = [0.0, 0.25, 0.55, 1.1, 1.65, 2.2]
row = 1
wr["A1"] = "Radial profiles at axial stations (r = 0 is the axis, r = 0.25 m is the wall)"; wr["A1"].font = BOLD
row = 3
for xi in stations:
    xv = xs[np.argmin(abs(xs - xi))]
    sel = np.where(np.abs(P[:, 0] - xv) < 1e-6)[0]
    sel = sel[np.argsort(P[sel, 1])]
    wr.cell(row, 1, f"Station x = {xv:.4f} m").font = BOLD
    names = ["r [m]", "r/R", "u axial [m/s]", "v radial [m/s]", "|V| [m/s]", "Static p [Pa]",
             "Mach", "T [K]", "ρ [kg/m³]", "Eddy viscosity [Pa·s]"]
    for j, h in enumerate(names, 1):
        c = wr.cell(row + 1, j, h); c.font, c.fill = H_FONT, H_FILL
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        wr.column_dimensions[get_column_letter(j)].width = 15
    R = P[:, 1].max()
    data = [[P[k, 1], P[k, 1] / R, U[k], V[k], speed[k], pd_["Pressure"][k], pd_["Mach"][k],
             pd_["Temperature"][k], pd_["Density"][k], pd_["Eddy_Viscosity"][k]] for k in sel]
    table(wr, row + 2, data, "0.000000")
    row += len(data) + 4

# ------------------------------------------------------------------ Wall
ww = wb.create_sheet("Wall")
srows = sorted(csv.DictReader(open("surface_flow.csv")), key=lambda r: float(r["x"]))
wcols = [("x", "x [m]"), ("Pressure", "Wall static p [Pa]"), ("Temperature", "Wall T [K]"),
         ("Skin_Friction_Coefficient_x", "Skin friction Cf_x"), ("Y_Plus", "y+"),
         ("Pressure_Coefficient", "Cp")]
header(ww, 1, [c[1] for c in wcols])
table(ww, 2, [[r[k] for k, _ in wcols] for r in srows])
line_chart(ww, "Wall skin friction", "Cf_x", 1, [4], len(srows), "H2")
line_chart(ww, "Wall y+", "y+", 1, [5], len(srows), "H19")

# ------------------------------------------------------------------ Convergence
wc = wb.create_sheet("Convergence")
hist = list(csv.reader(open("history.csv")))
hh = [h.strip().strip('"') for h in hist[0]]
keep = ["Inner_Iter", "rms[Rho]", "rms[RhoU]", "rms[RhoV]", "rms[RhoE]", "rms[nu]",
        "Avg_Mach(inlet)", "Avg_Mach(outlet)", "Avg_Press(inlet)", "Avg_Press(outlet)",
        "Avg_Massflow(inlet)", "Avg_Massflow(outlet)"]
idx = [hh.index(k) for k in keep]
wc["A1"] = "SU2 history of the final round (restarted from the earlier rounds); rms residuals are log10."
wc["A1"].font = Font(name=F, italic=True, color="595959")
for j, h in enumerate(keep, 1):
    c = wc.cell(2, j, h); c.font, c.fill = H_FONT, H_FILL
    wc.column_dimensions[get_column_letter(j)].width = 16
wc.freeze_panes = "A3"
table(wc, 3, [[r[i] for i in idx] for r in hist[1:]], "0.000000")
ch = LineChart(); ch.title = "Inlet Mach during the final round"; ch.height, ch.width = 8, 16
ch.add_data(Reference(wc, min_col=7, min_row=2, max_row=len(hist) + 1), titles_from_data=True)
ch.set_categories(Reference(wc, min_col=1, min_row=3, max_row=len(hist) + 1))
ch.x_axis.title, ch.y_axis.title = "Iteration", "Mach"
ch.roundedCorners = False; ch.legend.overlay = False; ch.title.overlay = False
ch.x_axis.title.overlay = False; ch.y_axis.title.overlay = False
ch.x_axis.delete = False; ch.y_axis.delete = False
ch.x_axis.tickLblSkip = 500
wc.add_chart(ch, "N3")

# ------------------------------------------------------------------ Full field
wf = wb.create_sheet("Full_Field")
fnames = ["x [m]", "r [m]", "u axial [m/s]", "v radial [m/s]", "|V| [m/s]", "Static p [Pa]", "Mach",
          "T [K]", "ρ [kg/m³]", "Laminar viscosity [Pa·s]", "Eddy viscosity [Pa·s]"]
header(wf, 1, fnames)
order = np.lexsort((P[:, 1], np.round(P[:, 0], 6)))
table(wf, 2, np.c_[P[order, 0], P[order, 1], U[order], V[order], speed[order], pd_["Pressure"][order],
                   pd_["Mach"][order], pd_["Temperature"][order], pd_["Density"][order],
                   pd_["Laminar_Viscosity"][order], pd_["Eddy_Viscosity"][order]].tolist(), "0.000000E+00")

wb.save(OUT)
print("wrote", OUT)
