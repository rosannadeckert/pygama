import numpy as np
from scipy.stats import exponnorm, norm

from pygama.math.functions.hpge_peak import hpge_peak
from pygama.math.functions.sum_dists import sum_dists


def test_hpge_peak_pdf():

    x = np.arange(-10, 10)

    sigma = 0.2
    mu = 2
    tau = 0.1
    htail = 0.75
    hstep = 0.5
    lower_range = np.inf
    upper_range = np.inf
    n_sig = 10
    n_bkg = 20

    pars = np.array(
        [mu, sigma, tau, htail, n_sig, hstep, lower_range, upper_range, n_bkg],
        dtype=float,
    )

    assert isinstance(hpge_peak, sum_dists)

    y_direct = hpge_peak.get_pdf(x, pars)
    scipy_exgauss = htail * exponnorm.pdf(
        -1 * x, tau / sigma, -1 * mu, sigma
    )  # to be equivalent to the scipy version, x -> -x, mu -> -mu, k -> k/sigma
    scipy_gauss = (1 - htail) * norm.pdf(x, mu, sigma)

    scipy_step = 1 + hstep * (norm.cdf(x, mu, sigma) * 2 - 1)

    maximum = (np.amax(x) - mu) / sigma
    minimum = (np.amin(x) - mu) / sigma
    normalization = sigma * (
        (
            maximum
            + hstep * maximum * (norm.cdf(maximum) * 2 - 1)
            + hstep * np.exp(-1 * maximum**2) / np.sqrt(np.pi)
        )
        - (
            minimum
            + hstep * minimum * (norm.cdf(minimum) * 2 - 1)
            + hstep * np.exp(-1 * minimum**2) / np.sqrt(np.pi)
        )
    )
    scipy_step = scipy_step / normalization

    scipy_y = n_sig * (scipy_exgauss + scipy_gauss) + n_bkg * scipy_step

    assert np.allclose(y_direct, scipy_y, rtol=1e-8)

    x_lo = -100
    x_hi = 100
    pars = np.insert(pars, 0, [x_lo, x_hi])
    y_sig, y_ext = hpge_peak.pdf_ext(x, pars)
    assert np.allclose(y_ext, scipy_y, rtol=1e-8)
    assert np.allclose(y_sig, n_sig + n_bkg, rtol=1e-8)


def test_hpge_peak_cdf():

    x = np.arange(-10, 10)

    sigma = 0.2
    mu = 2
    tau = 0.1
    htail = 0.75
    hstep = 0.5
    lower_range = np.inf
    upper_range = np.inf
    n_sig = 10
    n_bkg = 20

    pars = np.array(
        [mu, sigma, tau, htail, n_sig, hstep, lower_range, upper_range, n_bkg],
        dtype=float,
    )

    assert isinstance(hpge_peak, sum_dists)

    y_direct = hpge_peak.get_cdf(x, pars)

    scipy_exgauss = htail * (
        1 - exponnorm.cdf(-1 * x, tau / sigma, -1 * mu, sigma)
    )  # to be equivalent to the scipy version, x -> -x, mu -> -mu, k -> k/sigma
    scipy_gauss = (1 - htail) * norm.cdf(x, mu, sigma)

    z = (x - mu) / sigma
    scipy_step = sigma * (
        z
        + hstep * z * (2 * norm.cdf(z, 0, 1) - 1)
        + hstep * np.exp(-1 * z**2) / np.sqrt(np.pi)
    )
    maximum = (np.amax(x) - mu) / sigma
    minimum = (np.amin(x) - mu) / sigma
    normalization = sigma * (
        (
            maximum
            + hstep * maximum * (norm.cdf(maximum) * 2 - 1)
            + hstep * np.exp(-1 * maximum**2) / np.sqrt(np.pi)
        )
        - (
            minimum
            + hstep * minimum * (norm.cdf(minimum) * 2 - 1)
            + hstep * np.exp(-1 * minimum**2) / np.sqrt(np.pi)
        )
    )

    scipy_step /= normalization
    scipy_hstep = scipy_step + (1 - scipy_step[-1])

    scipy_y = n_sig * (scipy_exgauss + scipy_gauss) + n_bkg * scipy_hstep

    assert np.allclose(y_direct, scipy_y, rtol=1e-1)

    y_ext = hpge_peak.cdf_ext(x, pars)
    assert np.allclose(y_ext, scipy_y, rtol=1e-1)
