# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from functools import wraps

import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.model_selection import cross_val_score
from sklearn.metrics import accuracy_score

from stopit import ThreadingTimeout as Timeout, TimeoutException

import time
import warnings


def timeout(fn):
    @wraps(fn)
    def with_timeout(self, *args, **kwargs):
        if not hasattr(self, 'timeout') or self.timeout is None:
            return fn(self, *args, **kwargs)

        try:
            with Timeout(self.timeout, swallow_exc=False):
                res = fn(self, *args, **kwargs)
        except TimeoutException:
            # TODO log cause
            res = None

        return res
    return with_timeout


def eval_time(fn):
    @wraps(fn)
    def with_time(*args, **kwargs):
        start_time = time.time()

        res = fn(*args, **kwargs)
        if res is None:
            return None

        elapsed_time = np.log(time.time() - start_time + np.finfo(float).eps)
        return res, elapsed_time

    return with_time


def default_score(workflow, test_X, test_y):
    res_y = workflow.predict(test_X)
    return accuracy_score(test_y, res_y)


def _simple_eval(workflow, train_X, train_y, test_X, test_y, scorer=None):
    workflow.fit(train_X, train_y)
    if scorer is not None:
        return scorer(workflow, test_X, test_y)

    return default_score(workflow, test_X, test_y)


class EvaluatorBase(ABC):
    def __init__(self, timeout_s=None):
        self.train_X = None
        self.train_y = None

        self.timeout = timeout_s

    def __repr__(self):
        res = "{}".format(self.__class__.__name__)
        return res

    def fit(self, train_X, train_y):
        self.train_X = train_X
        self.train_y = train_y

    @abstractmethod
    def evaluate(self, workflow, scorer=None):
        pass

    @abstractmethod
    def reset(self):
        pass

    def check_is_fitted(self):
        if self.train_X is None or self.train_y is None:
            raise ValueError("Evaluator is not fitted with training data.")  # TODO specific

    @timeout
    @eval_time
    def score(self, workflow, scorer=None):
        self.check_is_fitted()

        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')

                return self.evaluate(workflow, scorer)
        # TODO think of a better exception handling
        except Exception as e:
            # TODO log exception
            return None


class CrossValEvaluator(EvaluatorBase):
    def __init__(self, cv_k=7, timeout_s=None):
        super().__init__(timeout_s)

        if cv_k < 0:
            raise AttributeError("Cross validation k must be greater than 0.")

        self.cv_k = cv_k

    def __repr__(self):
        res = super().__repr__()
        res += ", cv_k: {}".format(self.cv_k)
        return res

    def evaluate(self, workflow, scorer=None):
        scores = cross_val_score(workflow, self.train_X, self.train_y,
                                 cv=self.cv_k, scoring=scorer)
        return np.mean(scores)

    def reset(self):
        pass


class FixedTrainTestEvaluator(EvaluatorBase):
    def __init__(self, test_size=None, random_state=None, timeout_s=None):
        super().__init__(timeout_s)

        self.test_X = None
        self.test_y = None

        self.test_size = test_size
        self.random_state = random_state

    def __repr__(self):
        res = super().__repr__()
        res += ", test_size: {}".format(self.test_size)
        return res

    def fit(self, train_X, train_y):
        self.train_X, self.test_X, self.train_y, self.test_y = \
            train_test_split(train_X, train_y, test_size=self.test_size,
                             random_state=self.random_state)

    def check_is_fitted(self):
        super().check_is_fitted()
        if self.test_X is None or self.test_y is None:
            raise ValueError("Test data missing in evaluator.")

    def evaluate(self, workflow, scorer=None):
        return _simple_eval(workflow, self.train_X, self.train_y, self.test_X, self.test_y,
                            scorer=scorer)

    def reset(self):
        pass


class RandomTrainTestEvaluator(EvaluatorBase):
    def __init__(self, test_size=None, random_state=None, timeout_s=None):
        super().__init__(timeout_s)

        self.test_size = test_size

        self.rng = None
        if random_state is not None:
            if isinstance(random_state, np.random.RandomState):
                self.rng = random_state

            self.rng = np.random.RandomState(random_state)

    def __repr__(self):
        res = super().__repr__()
        res += ", test_size: {}".format(self.test_size)
        return res

    def evaluate(self, workflow, scorer=None):
        # random state is set only in the constructor
        train_X, test_X, train_y, test_y = train_test_split(self.train_X, self.train_y,
                                                            test_size=self.test_size,
                                                            random_state=self.rng)
        return _simple_eval(workflow, train_X, train_y, test_X, test_y,
                            scorer=scorer)

    def reset(self):
        pass


class TrainTestEvaluator(EvaluatorBase):
    def __init__(self, test_X, test_y, timeout_s=None):
        super().__init__(timeout_s)

        # training set is provided in fit, validation set is set on initialization
        self.test_X = test_X
        self.test_y = test_y

    def evaluate(self, workflow, scorer=None):
        return _simple_eval(workflow, self.train_X, self.train_y, self.test_X, self.test_y,
                            scorer=scorer)

    def reset(self):
        pass


class DataSampler:
    def __init__(self, sample_size=0.20, random_state=None, stratified=True):
        self.full_X = None
        self.full_y = None

        self.sample_size = sample_size
        self.stratified = stratified

        self.rng = None
        if random_state is not None:
            if isinstance(random_state, np.random.RandomState):
                self.rng = random_state

            self.rng = np.random.RandomState(random_state)

    def fit(self, full_X, full_y):
        self.full_X = full_X
        self.full_y = full_y

    def generate_sample(self):
        stratify = self.full_y if self.stratified else None

        _, sample_X, _, sample_y = train_test_split(self.full_X, self.full_y,
                                                    test_size=self.sample_size,
                                                    random_state=self.rng,
                                                    stratify=stratify)
        return sample_X, sample_y


class SampleCrossValEvaluator(CrossValEvaluator):
    def __init__(self, cv_k=7, timeout_s=None, sample_size=0.20, per_gen=False, random_state=None):
        super().__init__(cv_k=cv_k, timeout_s=timeout_s)

        self.per_gen = per_gen
        self.sampler = DataSampler(sample_size=sample_size, random_state=random_state)

    def __repr__(self):
        res = super().__repr__()
        res += ", sample_size: {}".format(self.sampler.sample_size)
        res += ", per_gen: {}".format(self.per_gen)
        return res

    def _reset_data(self):
        self.train_X, self.train_y = self.sampler.generate_sample()

    def fit(self, train_X, train_y):
        self.sampler.fit(train_X, train_y)
        self._reset_data()

    def evaluate(self, workflow, scorer=None):
        # generate sample for every evaluation
        if not self.per_gen:
            self._reset_data()

        return super().evaluate(workflow, scorer=scorer)

    def reset(self):
        # generate sample once per reset
        if self.per_gen:
            self._reset_data()


class SampleTrainTestEvaluator(FixedTrainTestEvaluator):
    def __init__(self, test_size=None, timeout_s=None, sample_size=0.20,
                 per_gen=False, random_state=None):

        self.per_gen = per_gen
        self.sampler = DataSampler(sample_size=sample_size, random_state=random_state)

        # rng should be set in DataSampler ctor
        super().__init__(test_size=test_size, random_state=self.sampler.rng, timeout_s=timeout_s)

    def __repr__(self):
        res = super().__repr__()
        res += ", sample_size: {}".format(self.sampler.sample_size)
        res += ", per_gen: {}".format(self.per_gen)
        return res

    def _fit_sample(self):
        train_X, train_y = self.sampler.generate_sample()

        super().fit(train_X, train_y)

    def fit(self, train_X, train_y):
        self.sampler.fit(train_X, train_y)

        self._fit_sample()

    def evaluate(self, workflow, scorer=None):
        # one sample per evaluation
        if not self.per_gen:
            self._fit_sample()

        return super().evaluate(workflow, scorer=scorer)

    def reset(self):
        # generate new fixed sample
        if self.per_gen:
            self._fit_sample()


_eval_names = {
    'crossval': CrossValEvaluator,
    'fixed': FixedTrainTestEvaluator,
    'per_ind': RandomTrainTestEvaluator,
    'train_test': TrainTestEvaluator,
    'sample_crossval': SampleCrossValEvaluator,
    'sample_train_test': SampleTrainTestEvaluator
}


def get_evaluator_cls(name):
    return _eval_names[name]
