import copy
import numpy as np
import numbers
from math import ceil
import warnings

from sklearn.base import TransformerMixin
from sklearn.tree import BaseDecisionTree
from sklearn.tree import _tree as _sklearn_tree
from sklearn.tree._criterion import BaseCriterion
from sklearn.tree._splitter import BaseSplitter
from sklearn.utils.validation import _check_sample_weight
from sklearn.utils import check_random_state

from . import _unsup_criterion, _unsup_splitter
from ._unsup_tree import UnsupervisedTree, UnsupervisedBestFirstTreeBuilder

DOUBLE = _sklearn_tree.DOUBLE

CRITERIA = {"twomeans": _unsup_criterion.TwoMeans}

SPLITTERS = {"best": _unsup_splitter.BestUnsupervisedSplitter}


class UnsupervisedDecisionTree(BaseDecisionTree, TransformerMixin):
    """Unsupervised decision tree.

    TODO: need to implement the logic fit/fit_transform/etc.

    Parameters
    ----------
    criterion : {"twomeans", "fastbic"}, default="twomeans"
        The function to measure the quality of a split. Supported criteria are
        "twomeans" for the variance impurity and "fastbic" for the
        BIC criterion.
    splitter : {"best", "random"}, default="best"
        The strategy used to choose the split at each node. Supported
        strategies are "best" to choose the best split and "random" to choose
        the best random split.
    max_depth : int, default=None
        The maximum depth of the tree. If None, then nodes are expanded until
        all leaves are pure or until all leaves contain less than
        min_samples_split samples.
    min_samples_split : int or float, default=2
        The minimum number of samples required to split an internal node:

        - If int, then consider `min_samples_split` as the minimum number.
        - If float, then `min_samples_split` is a fraction and
          `ceil(min_samples_split * n_samples)` are the minimum
          number of samples for each split.
    min_samples_leaf : int or float, default=1
        The minimum number of samples required to be at a leaf node.
        A split point at any depth will only be considered if it leaves at
        least ``min_samples_leaf`` training samples in each of the left and
        right branches.  This may have the effect of smoothing the model,
        especially in regression.

        - If int, then consider `min_samples_leaf` as the minimum number.
        - If float, then `min_samples_leaf` is a fraction and
          `ceil(min_samples_leaf * n_samples)` are the minimum
          number of samples for each node.
    min_weight_fraction_leaf : float, default=0.0
        The minimum weighted fraction of the sum total of weights (of all
        the input samples) required to be at a leaf node. Samples have
        equal weight when sample_weight is not provided.
    max_features : int, float or {"auto", "sqrt", "log2"}, default=None
        The number of features to consider when looking for the best split:

            - If int, then consider `max_features` features at each split.
            - If float, then `max_features` is a fraction and
              `max(1, int(max_features * n_features_in_))` features are considered at
              each split.
            - If "auto", then `max_features=sqrt(n_features)`.
            - If "sqrt", then `max_features=sqrt(n_features)`.
            - If "log2", then `max_features=log2(n_features)`.
            - If None, then `max_features=n_features`.
    max_leaf_nodes : int, default=None
        Grow a tree with ``max_leaf_nodes`` in best-first fashion.
        Best nodes are defined as relative reduction in impurity.
        If None then unlimited number of leaf nodes.
    random_state : int, RandomState instance or None, default=None
        Controls the randomness of the estimator. The features are always
        randomly permuted at each split, even if ``splitter`` is set to
        ``"best"``. When ``max_features < n_features``, the algorithm will
        select ``max_features`` at random at each split before finding the best
        split among them. But the best found split may vary across different
        runs, even if ``max_features=n_features``. That is the case, if the
        improvement of the criterion is identical for several splits and one
        split has to be selected at random. To obtain a deterministic behaviour
        during fitting, ``random_state`` has to be fixed to an integer.
        See how scikit-learn defines ``random_state`` for details.
    min_impurity_decrease : float, default=0.0
        A node will be split if this split induces a decrease of the impurity
        greater than or equal to this value.

        The weighted impurity decrease equation is the following::

            N_t / N * (impurity - N_t_R / N_t * right_impurity
                                - N_t_L / N_t * left_impurity)

        where ``N`` is the total number of samples, ``N_t`` is the number of
        samples at the current node, ``N_t_L`` is the number of samples in the
        left child, and ``N_t_R`` is the number of samples in the right child.

        ``N``, ``N_t``, ``N_t_R`` and ``N_t_L`` all refer to the weighted sum,
        if ``sample_weight`` is passed.
    """

    def __init__(
        self,
        *,
        criterion,
        splitter,
        max_depth,
        min_samples_split,
        min_samples_leaf,
        min_weight_fraction_leaf,
        max_features,
        max_leaf_nodes,
        random_state,
        min_impurity_decrease,
    ):
        super().__init__(
            criterion=criterion,
            splitter=splitter,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            min_weight_fraction_leaf=min_weight_fraction_leaf,
            max_features=max_features,
            max_leaf_nodes=max_leaf_nodes,
            random_state=random_state,
            min_impurity_decrease=min_impurity_decrease,
        )

    def fit(self, X, y=None, sample_weight=None, check_input=True):
        # Determine output settings
        n_samples, self.n_features_in_ = X.shape
        random_state = check_random_state(self.random_state)
        max_depth = np.iinfo(np.int32).max if self.max_depth is None else self.max_depth

        if isinstance(self.min_samples_leaf, numbers.Integral):
            min_samples_leaf = self.min_samples_leaf
        else:  # float
            min_samples_leaf = int(ceil(self.min_samples_leaf * n_samples))

        if isinstance(self.min_samples_split, numbers.Integral):
            min_samples_split = self.min_samples_split
        else:  # float
            min_samples_split = int(ceil(self.min_samples_split * n_samples))
            min_samples_split = max(2, min_samples_split)

        min_samples_split = max(min_samples_split, 2 * min_samples_leaf)

        if isinstance(self.max_features, str):
            if self.max_features == "auto":
                max_features = max(1, int(np.sqrt(self.n_features_in_)))
                warnings.warn(
                    "`max_features='auto'` has been deprecated in 1.1 "
                    "and will be removed in 1.3. To keep the past behaviour, "
                    "explicitly set `max_features='sqrt'`.",
                    FutureWarning,
                )
            elif self.max_features == "sqrt":
                max_features = max(1, int(np.sqrt(self.n_features_in_)))
            elif self.max_features == "log2":
                max_features = max(1, int(np.log2(self.n_features_in_)))
        elif self.max_features is None:
            max_features = self.n_features_in_
        elif isinstance(self.max_features, numbers.Integral):
            max_features = self.max_features
        else:  # float
            if self.max_features > 0.0:
                max_features = max(1, int(self.max_features * self.n_features_in_))
            else:
                max_features = 0

        self.max_features_ = max_features

        max_leaf_nodes = -1 if self.max_leaf_nodes is None else self.max_leaf_nodes

        if sample_weight is not None:
            sample_weight = _check_sample_weight(sample_weight, X, DOUBLE)

        # Set min_weight_leaf from min_weight_fraction_leaf
        if sample_weight is None:
            min_weight_leaf = self.min_weight_fraction_leaf * n_samples
        else:
            min_weight_leaf = self.min_weight_fraction_leaf * np.sum(sample_weight)

        criterion = self.criterion
        if not isinstance(criterion, BaseCriterion):
            criterion = CRITERIA[self.criterion]()
        else:
            # Make a deepcopy in case the criterion has mutable attributes that
            # might be shared and modified concurrently during parallel fitting
            criterion = copy.deepcopy(criterion)

        splitter = self.splitter
        if not isinstance(self.splitter, BaseSplitter):
            splitter = SPLITTERS[self.splitter](
                criterion,
                self.max_features_,
                min_samples_leaf,
                min_weight_leaf,
                random_state,
            )

        self.tree_ = UnsupervisedTree(
            self.n_features_in_,
            # TODO: tree shouldn't need this in this case
            np.array([1] * self.n_outputs_, dtype=np.intp),
            self.n_outputs_,
        )

        # Use BestFirst if max_leaf_nodes given; use DepthFirst otherwise
        if max_leaf_nodes < 0:
            builder = UnsupervisedDepthFirstTreeBuilder(
                splitter,
                min_samples_split,
                min_samples_leaf,
                min_weight_leaf,
                max_depth,
                self.min_impurity_decrease,
            )
        else:
            builder = UnsupervisedBestFirstTreeBuilder(
                splitter,
                min_samples_split,
                min_samples_leaf,
                min_weight_leaf,
                max_depth,
                max_leaf_nodes,
                self.min_impurity_decrease,
            )

        builder.build(self.tree_, X, y, sample_weight)
        return self

    def transform(self, X):
        """Transform each sample to an array of the leaf nodes that it falls into.

        For a single tree, each sample falls into exactly one leaf.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features_in_)
            The input data array.

        Returns
        -------
        X_new : ndarray array of shape (n_samples, n_features_new)
            Transformed array.
        """
        out = self.tree_.transform(X)
        return out

    def predict(self, X, check_input=True):
        raise RuntimeError(f"not allowed")
