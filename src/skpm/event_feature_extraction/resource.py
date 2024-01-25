import warnings

import numpy as np
from pandas import DataFrame
from scipy.sparse.csgraph import connected_components
from sklearn.base import (
    BaseEstimator,
    TransformerMixin,
    check_is_fitted,
)

from skpm.utils import validate_columns
from skpm.config import EventLogConfig as elc


class ResourcePoolExtractor(TransformerMixin, BaseEstimator):
    """
    Proposed in [1]. Code adapted from [2].

    TODO: implement other distance metrics.

    References
    ----------
    [1] Minseok Song, Wil M.P. van der Aalst. Towards comprehensive support for organizational mining, Decision Support Systems (2008).
    [2] https://github.com/AdaptiveBProcess/GenerativeLSTM

    Notes
    -----
    - distance metrics: (dis)similarity between two vectors (variables). It must
    satisfy the following mathematical properties: d(x,x) = 0, d(x,y) >= 0,
    d(x,y) = d(y,x), d(x,z) <= d(x,y) + d(y,z)
    - correlation coeficients: statistical relationships between vectors (variables)
    that quantify how much they are related.

    The original paper mentions Pearson correlation as a distance metric. For
    academic purposes, it's crucial to grasp the distinction since correlation
    does not satisfy the triangular inequality. Yet, there are instances where
    I think correlation can be informally employed as a 'similarity' measure.
    In the context of organizational mining, I believe statistical relationships
    and similarity ultimately serve the same purpose.

    """

    def __init__(self, threshold=0.7):
        # the original implementation uses 0.7 as threshold but in the argparser they set 0.85
        self.threshold = threshold

    def get_feature_names_out(self):
        return ["resource_roles"]

    def fit(self, X: DataFrame, y=None):
        X = self._validate_data(X)

        # defining vocabs for activities and resources
        self.atoi_, self.itoa_ = self._define_vocabs(X[elc.activity].unique())
        self.rtoi_, self.itor_ = self._define_vocabs(X[elc.resource].unique())

        X[elc.activity] = X[elc.activity].map(self.atoi_)
        X[elc.resource] = X[elc.resource].map(self.rtoi_)

        # building a pairwise frequency matrix
        freq_matrix = X.groupby([elc.activity, elc.resource]).value_counts().to_dict()

        # building an activity profile for each resource

        # matrix profile: rows = resources, columns = activities
        # the unown labels are generating a row of zeros, and this is throwing a warning when calculating the correlation matrix: TODO
        # https://stackoverflow.com/questions/45897003/python-numpy-corrcoef-runtimewarning-invalid-value-encountered-in-true-divide
        profiles = np.zeros((len(self.rtoi_), len(self.atoi_)), dtype=int)
        for pair_ar, freq in freq_matrix.items():
            # pair_ar = (activity, resource); order defined by groupby
            profiles[pair_ar[1], pair_ar[0]] = freq

        # correlation matrix
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            corr = np.corrcoef(
                profiles
            )  # TODO: include similarity/correlation metric parameter

        np.fill_diagonal(
            corr, 0
        )  # the original paper does not consider self-relationship

        # subgraphs as roles
        n_components, labels = connected_components(
            corr > self.threshold, directed=False
        )

        sub_graphs = list()
        for i in range(n_components):
            sub_graphs.append(set(np.where(labels == i)[0]))

        # role definition
        self.resource_to_roles_ = dict()
        for role_ix, role in enumerate(sub_graphs):
            for user_id in role:
                self.resource_to_roles_[user_id] = role_ix

        return self

    def transform(self, X: DataFrame, y=None):
        check_is_fitted(self, "resource_to_roles_")
        X = self._validate_data(X)
        resource_roles = X[elc.resource].map(self.resource_to_roles_).values
        return resource_roles

    def _validate_data(self, X: DataFrame):
        assert isinstance(X, DataFrame), "Input must be a dataframe."
        x = X.copy()
        x.reset_index(drop=True, inplace=True)
        columns = validate_columns(
            input_columns=x.columns, required=[elc.activity, elc.resource]
        )
        x = x[columns]

        if x[elc.activity].isnull().any():
            raise ValueError("Activity column contains null values.")
        if x[elc.resource].isnull().any():
            raise ValueError("Resource column contains null values.")

        # i.e. if fitted, check unkown labels
        if hasattr(self, "resource_to_roles_"):
            x[elc.resource] = self._check_unknown(
                x[elc.resource].values, self.rtoi_.keys(), "resource"
            )
            x[elc.activity] = self._check_unknown(
                x[elc.activity].values, self.atoi_.keys(), "activity"
            )

            x[elc.activity] = x[elc.activity].map(self.atoi_)
            x[elc.resource] = x[elc.resource].map(self.rtoi_)

        return x

    def _check_unknown(self, input: np.ndarray, vocab: np.ndarray, name: str):
        unkown = set(input) - set(vocab)
        if unkown:
            warnings.warn(
                message=(f"Unknown {name} labels: {unkown}"),
                category=UserWarning,
                stacklevel=2,
            )

        input = np.array(["UNK" if x in unkown else x for x in input])
        # input = input.replace(unkown, "UNK")
        return input

    def _define_vocabs(self, unique_labels: np.ndarray):
        stoi, itos = {"UNK": 0}, {0: "UNK"}
        stoi.update({label: i + 1 for i, label in enumerate(unique_labels)})
        itos.update({i + 1: label for i, label in enumerate(unique_labels)})
        return stoi, itos
