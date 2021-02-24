import sys
import numpy as np
import numbers

from scipy.special import digamma
from scipy.special import polygamma
from statsmodels.api import GLM
import statsmodels
import statsmodels.api as sm


def trigamma(x):
    """Trigamma function.

    Parameters
    ----------
    x: float
    """
    return polygamma(1, x)


def _process_y(y):
    if not isinstance(y, np.ndarray):
        y = np.array(y)
    y = np.asarray(y, dtype=int)
    y = np.squeeze(y)
    return y


def lookup_table(y):
    y = np.squeeze(y)
    y_bc = np.bincount(y)
    y_i = np.nonzero(y_bc)[0]
    y_lookup = np.vstack((y_i, y_bc[y_i])).T
    return y_lookup


def theta_nb_score(y, mu, theta, fast=True):

    y_lookup = None
    N = len(y)
    if fast:
        # create a lookup table for y
        # Inspired from glmGamPoi, Ahlmann-Eltze and Huber (2020)
        y_lookup = lookup_table(y)
        digamma_sum = np.dot(digamma(y_lookup[:, 0] + theta), y_lookup[:, 1])
        digamma_theta = digamma(theta) * N
        mu_term = (np.log(theta) - np.log(mu + theta) + 1) * N
        y_term = sum((y + theta) / (mu + theta))

        lld = digamma_sum - digamma_theta - y_term + mu_term
        return lld
    else:
        digamma_sum = digamma(y + theta)
        digamma_theta = digamma(theta)
        mu_term = np.log(theta) - np.log(mu + theta) + 1
        y_term = (y + theta) / (mu + theta)

        lld = digamma_sum - digamma_theta - y_term + mu_term
        return lld.sum()


def theta_nb_hessian(y, mu, theta, fast=True):
    y_lookup = None
    N = len(y)
    if fast:
        # create a lookup table for y
        # Inspired from glmGamPoi, Ahlmann-Eltze and Huber (2020)
        y_lookup = lookup_table(y)
        trigamma_sum = np.dot(trigamma(y_lookup[:, 0] + theta), y_lookup[:, 1])
        trigamma_theta = trigamma(theta) * N
        mu_term = (1 / theta - 2 / (mu + theta)) * N
        y_term = ((y + theta) / (mu + theta) ** 2).sum()
        lldd = trigamma_sum - trigamma_theta + y_term + mu_term
        return lldd
    else:
        trigamma_sum = trigamma(y + theta)
        trigamma_theta = trigamma(theta)

        mu_term = 1 / theta - 2 / (mu + theta)
        y_term = (y + theta) / (mu + theta) ** 2
        lldd = trigamma_sum - trigamma_theta + y_term + mu_term
        return lldd.sum()


def estimate_mu_glm(y, model_matrix):
    y = _process_y(y)
    model = sm.GLM(y, model_matrix, family=sm.families.Poisson())
    fit = model.fit()
    mu = fit.predict()
    return {"coef": fit.params, "mu": mu[0]}


def estimate_mu_poisson(y, model_matrix):
    y = _process_y(y)
    model = statsmodels.discrete.discrete_model.Poisson(y, model_matrix)
    fit = model.fit(disp=False)
    mu = fit.predict()
    return {"coef": fit.params, "mu": mu[0]}


def theta_ml(y, mu, max_iters=20, tol=1e-4):
    y = _process_y(y)
    mu = np.squeeze(mu)

    N = len(y)
    theta = N / sum((y / mu - 1) ** 2)
    for i in range(max_iters):
        theta = abs(theta)

        score_diff = theta_nb_score(y, mu, theta)
        # if first diff is negative, there is no maximum
        if score_diff < 0:
            return np.inf
        delta_theta = score_diff / theta_nb_hessian(y, mu, theta)
        theta = theta - delta_theta

        if np.abs(delta_theta) <= tol:
            return theta

    if theta < 0:
        theta = np.inf

    return theta


def fit_tensorflow(response, model_matrix):
    # Not being used currently
    import tensorflow as tf
    import tensorflow_probability as tfp

    @tf.function(autograph=False)
    def tfp_fit(response, model_matrix):
        return tfp.glm.fit(
            model_matrix=model_matrix,
            response=response,
            model=tfp.glm.NegativeBinomial(),
            maximum_iterations=100,
        )

    def do_tfp_fit(response, model_matrix, design_info_cols):
        [model_coefficients, linear_response, is_converged, num_iter] = [
            t.numpy()
            for t in tfp_fit(
                response,
                model_matrix,
            )
        ]
        theta = linear_response.mean() ** 2 / (
            linear_response.var() - linear_response.mean()
        )
        if theta < 0:
            theta = -theta
        theta = 1 / theta
        params = dict(zip(design_info_cols, model_coefficients))
        params["theta"] = theta
        return params