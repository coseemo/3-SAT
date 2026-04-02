import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from timeit import default_timer as timer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

SOLVER_BACKTRACKING = "backtracking"
SOLVER_HEURISTICS   = "heuristics"
SOLVER_MINISAT      = "minisat"
ALL_SOLVERS         = [SOLVER_BACKTRACKING, SOLVER_HEURISTICS, SOLVER_MINISAT]

def carica_config(path_config: str) -> dict:
    """Legge il file YAML e restituisce il dizionario di configurazione."""
    config_path = Path(path_config)
    if not config_path.exists():
        print(f"[ERRORE] File di configurazione non trovato: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config

def genera_formula_3sat(num_variabili: int, num_clausole: int) -> list[list[int]]:
    """Genera una formula 3-SAT casuale."""
    formula = []
    for _ in range(num_clausole):
        clausola = set()
        usate = []
        while len(clausola) < 3:
            while True:
                var = random.randint(1, num_variabili)
                if var not in usate:
                    usate.append(var)
                    break
            if random.choice([True, False]):
                var = -var
            clausola.add(var)
        formula.append(list(clausola))
    return formula

#MiniSAT

def _formula_to_dimacs(formula: list, num_variabili: int) -> str:
    linee = [f"p cnf {num_variabili} {len(formula)}"]
    for clausola in formula:
        linee.append(" ".join(map(str, clausola)) + " 0")
    return "\n".join(linee)


def risolvi_con_minisat(formula: list, num_variabili: int, debug: bool = False) -> dict | None:
    """Risolve con MiniSAT esterno; restituisce l'assegnamento o None se UNSAT."""
    input_file = output_file = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as f:
            input_file = f.name
            dimacs = _formula_to_dimacs(formula, num_variabili)
            f.write(dimacs)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            output_file = f.name

        result = subprocess.run(
            ["minisat", input_file, output_file],
            capture_output=True, text=True, timeout=30,
        )

        with open(output_file, "r") as f:
            lines = f.read().strip().split("\n")

        if not lines:
            return None

        if lines[0].strip() == "SAT":
            if len(lines) > 1:
                assignment = {}
                for lit in lines[1].split():
                    if lit != "0":
                        v = abs(int(lit))
                        assignment[v] = int(lit) > 0
                return assignment
            return {}
        return None  # UNSAT

    except subprocess.TimeoutExpired:
        if debug:
            print("  [MiniSAT] Timeout")
        return None
    except FileNotFoundError:
        print("[ERRORE] MiniSAT non trovato. Installalo con: sudo apt-get install minisat")
        sys.exit(1)
    except Exception as e:
        if debug:
            print(f"  [MiniSAT] Errore: {e}")
        return None
    finally:
        for p in (input_file, output_file):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
                    
#Backtracking

def _semplifica(formula: list, var: int, valore: bool) -> list | None:
    risultato = []
    for clausola in formula:
        if valore and var in clausola:
            continue
        if not valore and -var in clausola:
            continue
        nuova = [l for l in clausola if l != (var if not valore else -var)]
        if not nuova:
            return None  #clausola vuota -> conflitto
        risultato.append(nuova)
    return risultato


def _backtrack(formula: list, variabili: list, assegnamento: dict,
               usa_euristiche: bool, debug: bool) -> dict | None:
    if not formula:
        return assegnamento
    if any(not c for c in formula):
        return None

    # Propagazione unitaria
    if usa_euristiche:
        unitarie = [c[0] for c in formula if len(c) == 1]
        for lit in unitarie:
            var, val = (lit, True) if lit > 0 else (-lit, False)
            formula = _semplifica(formula, var, val)
            if formula is None:
                return None
            assegnamento[var] = val
            if var in variabili:
                variabili = [v for v in variabili if v != var]

        if not variabili:
            return assegnamento

    var = variabili[0]
    resto = variabili[1:]

    for valore in (True, False):
        nuovo_ass = {**assegnamento, var: valore}
        nuova_formula = _semplifica(formula, var, valore)
        if nuova_formula is not None:
            ris = _backtrack(nuova_formula, resto, nuovo_ass, usa_euristiche, debug)
            if ris is not None:
                return ris

    return None

def risolvi_con_backtracking(formula: list, num_variabili: int,
                              usa_euristiche: bool, debug: bool = False) -> dict | None:
    variabili = list(range(1, num_variabili + 1))
    return _backtrack(formula, variabili, {}, usa_euristiche, debug)

def risolvi(formula: list, num_variabili: int, solver: str, debug: bool = False) -> dict | None:
    if solver == SOLVER_MINISAT:
        return risolvi_con_minisat(formula, num_variabili, debug)
    euristiche = (solver == SOLVER_HEURISTICS)
    return risolvi_con_backtracking(formula, num_variabili, euristiche, debug)

def raccogli_probabilita(num_var: int, lista_clausole: list[int],
                          num_test: int, solver: str) -> tuple[list, list, list]:
    """Restituisce (rapporti, percentuali_sat, tempi_medi)."""
    rapporti, percentuali, tempi = [], [], []
    for m in lista_clausole:
        ratio = m / num_var
        soddisfatte = 0
        t_totale = 0.0
        for _ in range(num_test):
            formula = genera_formula_3sat(num_var, m)
            t0 = timer()
            ris = risolvi(formula, num_var, solver)
            t_totale += timer() - t0
            if ris is not None:
                soddisfatte += 1
        rapporti.append(ratio)
        percentuali.append(soddisfatte / num_test * 100)
        tempi.append(t_totale / num_test)
        print(f"  [{solver}] N={num_var}, M/N={ratio:.2f}, "
              f"SAT={soddisfatte}/{num_test}, t_medio={t_totale/num_test:.6f}s")
    return rapporti, percentuali, tempi


def raccogli_distribuzione(num_var: int, lista_clausole: list[int],
                            punti: int, solver: str) -> tuple[list, list, list]:
    """Restituisce (rapporti, tempi, flag_sat) punto per punto."""
    rapporti, tempi, sat_flags = [], [], []
    for m in lista_clausole:
        ratio = m / num_var
        print(f"  [{solver}] distribuzione N={num_var}, M/N={ratio:.2f}")
        for _ in range(punti):
            formula = genera_formula_3sat(num_var, m)
            t0 = timer()
            ris = risolvi(formula, num_var, solver)
            tempi.append(timer() - t0)
            rapporti.append(ratio)
            sat_flags.append(1 if ris is not None else 0)
    return rapporti, tempi, sat_flags

ETICHETTE = {
    SOLVER_BACKTRACKING: "Backtracking",
    SOLVER_HEURISTICS:   "Backtracking + Euristiche",
    SOLVER_MINISAT:      "MiniSAT",
}

SUFFISSI = {
    SOLVER_BACKTRACKING: "",
    SOLVER_HEURISTICS:   "_H",
    SOLVER_MINISAT:      "_MiniSAT",
}


def _save(fig, output_dir: str, nome_base: str, formati: list[str]):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for fmt in formati:
        path = Path(output_dir) / f"{nome_base}.{fmt}"
        fig.savefig(path)
        print(f"  Salvato: {path}")


def plot_probabilita(dati_solver: dict, valori_n: list,
                     palette: list, output_dir: str, formati: list):
    """Grafico percentuale soddisfacibili per ogni solver."""
    fig, ax = plt.subplots()
    for solver, dati_n in dati_solver.items():
        for i, (rapporti, percentuali, _) in enumerate(dati_n):
            etichetta = f"{ETICHETTE[solver]} N={valori_n[i]}" if len(dati_solver) > 1 \
                        else f"N={valori_n[i]}"
            ax.scatter(rapporti, percentuali, s=25, alpha=0.6,
                       color=palette[i % len(palette)], label=etichetta)

    ax.set_title("Percentuale soddisfacibili")
    ax.set_xlabel("Rapporto M/N")
    ax.set_ylabel("Percentuale soddisfacibili (%)")
    ax.set_ylim(0, 100)
    ax.set_xlim(1, 9)
    ax.set_xticks(range(1, 10))
    ax.grid(True)
    ax.legend(fontsize=7)

    suffisso = "_".join(SUFFISSI[s].strip("_") or "BT" for s in dati_solver)
    _save(fig, output_dir, f"plt_prob_{suffisso}", formati)
    plt.close(fig)


def plot_tempi(dati_solver: dict, valori_n: list,
               palette: list, output_dir: str, formati: list):
    """Grafico tempi medi per ogni solver."""
    fig, ax = plt.subplots()
    for solver, dati_n in dati_solver.items():
        for i, (rapporti, _, tempi) in enumerate(dati_n):
            etichetta = f"{ETICHETTE[solver]} N={valori_n[i]}" if len(dati_solver) > 1 \
                        else f"N={valori_n[i]}"
            ax.scatter(rapporti, tempi, s=25, alpha=0.6,
                       color=palette[i % len(palette)], label=etichetta)

    ax.set_title("Tempi di esecuzione medi")
    ax.set_xlabel("Rapporto M/N")
    ax.set_ylabel("Tempo medio (s)")
    ax.set_xlim(1, 9)
    ax.set_xticks(range(1, 10))
    ax.grid(True)
    ax.legend(fontsize=7)

    suffisso = "_".join(SUFFISSI[s].strip("_") or "BT" for s in dati_solver)
    _save(fig, output_dir, f"plt_times_{suffisso}", formati)
    plt.close(fig)


def plot_distribuzione(rapporti: list, tempi: list, sat_flags: list,
                       num_var: int, solver: str,
                       output_dir: str, formati: list):
    """Scatter plot distribuzione SAT/UNSAT nel tempo."""
    fig, ax = plt.subplots()
    colori = ["royalblue" if s == 1 else "orangered" for s in sat_flags]
    ax.scatter(rapporti, tempi, c=colori, s=18, alpha=0.6)

    #Legenda manuale
    from matplotlib.lines import Line2D
    legenda = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="royalblue",
               markersize=8, label="SAT"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="orangered",
               markersize=8, label="UNSAT"),
    ]
    ax.legend(handles=legenda)
    ax.set_title(f"Distribuzione tempi N={num_var} — {ETICHETTE[solver]}")
    ax.set_xlabel("Rapporto M/N")
    ax.set_ylabel("Tempo di esecuzione (s)")
    ax.set_xlim(1, 9)
    ax.set_xticks(range(1, 10))
    ax.grid(True)

    suf = SUFFISSI[solver].strip("_") or "BT"
    _save(fig, output_dir, f"plt_sat_{suf}", formati)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisi sperimentale 3-SAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python sat_solver.py --solver backtracking
  python sat_solver.py --solver heuristics
  python sat_solver.py --solver minisat
  python sat_solver.py --all
  python sat_solver.py --all --config config.yaml
  python sat_solver.py --solver backtracking --debug
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--solver",
        choices=ALL_SOLVERS,
        metavar="{" + "|".join(ALL_SOLVERS) + "}",
        help="Solver da usare per i test",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Esegui tutti e tre i solver e confronta i risultati",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Percorso del file YAML di configurazione (default: config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Abilita output di debug",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    cfg  = carica_config(args.config)

    #Leggo configurazione
    num_tests      = cfg["experiment"]["num_tests"]
    punti_ratio    = cfg["experiment"]["points_per_ratio"]
    valori_n       = cfg["variables"]["values"]
    n_dettagliato  = cfg["variables"]["detailed"]
    output_dir     = cfg["output"]["dir"]
    formati        = cfg["output"]["formats"]
    palette        = cfg["plots"]["palette"]
    gen_prob       = cfg["plots"]["probability"]
    gen_tempi      = cfg["plots"]["times"]
    gen_dist       = cfg["plots"]["distribution"]

    #Determino lista solver da testare
    if args.all:
        solvers = ALL_SOLVERS
    else:
        solvers = [args.solver]

    print(f"Solver selezionati: {solvers}")
    print(f"Configurazione: N={valori_n}, test={num_tests}, "
          f"punti/ratio={punti_ratio}, output='{output_dir}'")
    print("-" * 60)

    if gen_prob or gen_tempi:
        # dati_solver[solver] = lista di (rapporti, percentuali, tempi) per ogni N
        dati_solver: dict[str, list] = {}

        for solver in solvers:
            print(f"\n[{solver}] Raccolta dati probabilità...")
            dati_n = []
            for n in valori_n:
                step = max(1, n // 10)
                clausole = np.arange(n, n * 9 + 1, step).tolist()
                rapporti, percentuali, tempi = raccogli_probabilita(
                    n, clausole, num_tests, solver
                )
                dati_n.append((rapporti, percentuali, tempi))
            dati_solver[solver] = dati_n

        if gen_prob:
            print("\nGenerazione grafico probabilità...")
            plot_probabilita(dati_solver, valori_n, palette, output_dir, formati)

        if gen_tempi:
            print("\nGenerazione grafico tempi medi...")
            plot_tempi(dati_solver, valori_n, palette, output_dir, formati)

    if gen_dist:
        step = max(1, n_dettagliato // 10)
        clausole_det = np.arange(n_dettagliato, n_dettagliato * 9 + 1, step).tolist()

        for solver in solvers:
            print(f"\n[{solver}] Raccolta dati distribuzione N={n_dettagliato}...")
            rapporti, tempi, flags = raccogli_distribuzione(
                n_dettagliato, clausole_det, punti_ratio, solver
            )
            print(f"\nGenerazione grafico distribuzione [{solver}]...")
            plot_distribuzione(rapporti, tempi, flags, n_dettagliato,
                               solver, output_dir, formati)

    print("\nAnalisi completata!")


if __name__ == "__main__":
    main()
