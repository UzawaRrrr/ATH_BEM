from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from tqdm import trange


Individual = dict[str, float]
Bounds = dict[str, tuple[float, float]]


@dataclass
class GAResult:
    best_individual: Individual
    best_fitness: float
    history: list[float]
    generations: int


def sample_individual(rng: random.Random, bounds: Bounds) -> Individual:
    return {
        key: rng.uniform(limit[0], limit[1])
        for key, limit in bounds.items()
    }


def mutate_individual(rng: random.Random, individual: Individual, bounds: Bounds, mutation_scale: float) -> Individual:
    child: Individual = {}
    for key, value in individual.items():
        low, high = bounds[key]
        span = high - low
        mutated = value + rng.gauss(0.0, span * mutation_scale)
        child[key] = min(max(mutated, low), high)
    return child


def crossover(rng: random.Random, a: Individual, b: Individual) -> Individual:
    return {key: (a[key] if rng.random() < 0.5 else b[key]) for key in a}


def run_ga(
    evaluate_fn: Callable[[Individual], float],
    bounds: Bounds,
    population_size: int,
    generations: int,
    mutation_scale: float,
    elite_count: int,
    seed: int,
) -> GAResult:
    rng = random.Random(seed)
    population = [sample_individual(rng, bounds) for _ in range(population_size)]

    best_individual = population[0]
    best_fitness = float("-inf")
    history: list[float] = []

    for _ in trange(generations, desc="GA generations"):
        scored = [(evaluate_fn(ind), ind) for ind in population]
        scored.sort(key=lambda item: item[0], reverse=True)
        generation_best_fitness, generation_best_individual = scored[0]

        if generation_best_fitness > best_fitness:
            best_fitness = generation_best_fitness
            best_individual = dict(generation_best_individual)

        history.append(generation_best_fitness)

        elites = [dict(ind) for _, ind in scored[: max(1, elite_count)]]
        next_population: list[Individual] = elites[:]

        while len(next_population) < population_size:
            parent_a = rng.choice(scored[: max(2, population_size // 2)])[1]
            parent_b = rng.choice(scored[: max(2, population_size // 2)])[1]
            child = crossover(rng, parent_a, parent_b)
            child = mutate_individual(rng, child, bounds, mutation_scale)
            next_population.append(child)

        population = next_population

    return GAResult(
        best_individual=best_individual,
        best_fitness=best_fitness,
        history=history,
        generations=generations,
    )

