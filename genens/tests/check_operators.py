from genens import GenensClassifier
from genens.workflow.evaluate import SampleCrossValEvaluator
from genens.gp.operators import mutate_node_swap, mutate_node_args, mutate_subtree, crossover_one_point
from genens.tests.datasets.load_datasets import load_dataset


if __name__ == "__main__":
    X, y = load_dataset('wilt')

    eval = SampleCrossValEvaluator(cv_k=5, per_gen=True)
    clf = GenensClassifier(n_jobs=1, pop_size=12, n_gen=2, evaluator=eval)

    clf.fit(X, y)
    pop = clf._population

    print(pop)

    for tree1, _ in zip(pop[1:], pop[:-1]):
        tree1, tree2 = crossover_one_point(tree1, tree1)
        mut1 = mutate_subtree(clf._toolbox, tree1)

    pass