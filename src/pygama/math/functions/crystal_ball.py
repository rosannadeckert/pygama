"""
Crystal ball distributions for Pygama
"""

import math

import numba as nb
import numpy as np
from math import erf

from pygama.math.functions.pygama_continuous import pygama_continuous 

kwd = {"parallel": False, "fastmath": True}
kwd_parallel = {"parallel": True, "fastmath": True}


@nb.njit(**kwd_parallel)
def nb_crystal_ball_pdf(x: np.ndarray, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
    r"""
    PDF of a power-law tail plus gaussian. Its range of support is :math:`x\in\mathbb{R}, \beta>0, m>1`. It computes:


    .. math::
        pdf(x, \beta, m, \mu, \sigma) =  \begin{cases}NA(B-\frac{x-\mu}{\sigma})^{-m} \quad \frac{x-\mu}{\sigma}\leq -\beta \\ Ne^{-(\frac{x-\mu}{\sigma})^2/2} \quad \frac{x-\mu}{\sigma}>-\beta\end{cases}


    Where 


    .. math::
        A =  \frac{m^m}{\beta^m}e^{-\beta^2/2} \\
        B = \frac{m}{\beta}-\beta \\
        N =  \frac{1}{\sigma \frac{m e^{-\beta^2/2}}{\beta(m-1)} + \sigma \sqrt{\frac{\pi}{2}}\left(1+\text{erf}\left(\frac{\beta}{\sqrt{2}}\right)\right)}


    As a Numba vectorized function, it runs slightly faster than
    'out of the box' functions.

    Parameters
    ----------
    x
        The input data
    beta
        The point where the pdf changes from power-law to Gaussian
    m
        The power of the power-law tail
    mu
        The amount to shift the distribution
    sigma
        The amount to scale the distribution
    """

    if (beta <= 0) or (m <= 1):
        raise ValueError("beta must be greater than 0, and m must be greater than 1")

    # Define some constants to calculate the function
    const_A =(m/np.abs(beta))**m * np.exp(-1*beta**2/2.0)
    const_B = m/np.abs(beta) - np.abs(beta)

    N = 1.0/(m/np.abs(beta)/(m-1)*np.exp(-beta**2/2.0) + np.sqrt(np.pi/2)*(1+erf(np.abs(beta)/np.sqrt(2.0))))

    y = np.empty_like(x, dtype=np.float64)
    for i in nb.prange(x.shape[0]):
        # Shift the distribution
        y[i] = (x[i]-mu)/sigma
        # Check if it is powerlaw
        if y[i] <= -1*beta:
            y[i] = N*const_A*(const_B-y[i])**(-1*m)/sigma
        # If it isn't power law, then it Gaussian
        else:
            y[i]  = N*np.exp(-1*y[i]**2/2)/sigma

    return y


@nb.njit(**kwd_parallel)
def nb_crystal_ball_cdf(x: np.ndarray, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
    r"""
    CDF for power-law tail plus gaussian. Its range of support is :math:`x\in\mathbb{R}, \beta>0, m>1`. It computes: 


    .. math:: 
        cdf(x, \beta, m,  \mu, \sigma)= \begin{cases}  NA\sigma\frac{(B-\frac{x-\mu}{\sigma})^{1-m}}{m-1} \quad , \frac{x-\mu}{\sigma} \leq -\beta \\ NA\sigma\frac{(B+\beta)^{1-m}}{m-1} + N\sigma \sqrt{\frac{\pi}{2}}\left(\text{erf}\left(\frac{x-\mu}{\sigma \sqrt{2}}\right)+\text{erf}\left(\frac{\beta}{\sqrt{2}}\right)\right)  \quad , \frac{x-\mu}{\sigma} >  -\beta \end{cases}


    Where 


    .. math::
        A =  \frac{m^m}{\beta^m}e^{-\beta^2/2} \\
        B = \frac{m}{\beta}-\beta \\
        N =  \frac{1}{\sigma \frac{m e^{-\beta^2/2}}{\beta(m-1)} + \sigma \sqrt{\frac{\pi}{2}}\left(1+\text{erf}\left(\frac{\beta}{\sqrt{2}}\right)\right)}


    As a Numba vectorized function, it runs slightly faster than
    'out of the box' functions.

    Parameters
    ----------
    x
        The input data
    beta
        The point where the cdf changes from power-law to Gaussian
    m
        The power of the power-law tail
    mu
        The amount to shift the distribution
    sigma
        The amount to scale the distribution
    """

    if (beta <= 0) or (m <= 1):
        raise ValueError("beta must be greater than 0, and m must be greater than 1")
    # Define some constants to calculate the function
    const_A =(m/np.abs(beta))**m * np.exp(-1*beta**2/2.0)
    const_B = m/np.abs(beta) - np.abs(beta)

    # Calculate the normalization constant
    N = 1.0/((np.sqrt(np.pi/2)*(erf(beta/np.sqrt(2)) + 1))\
        + ((const_A*(const_B+beta)**(1-m))/(m-1)))

    y = np.empty_like(x, dtype = np.float64)

    # Check if it is in the power law part
    for i in nb.prange(x.shape[0]):
        # Shift the distribution
        y[i] = (x[i]-mu)/sigma
        if y[i] <= -1*beta:
            y[i] = N*const_A*((const_B-y[i])**(1-m))/(m-1)

        # If it isn't in the power law, then it is Gaussian
        else:
            y[i] = const_A*N*((const_B+beta)**(1-m))/(m-1)\
                + N*np.sqrt(np.pi/2)*(erf(beta/np.sqrt(2))+erf(y[i]/np.sqrt(2)))
    return y


@nb.njit(**kwd)
def nb_crystal_ball_scaled_pdf(x: np.ndarray, area: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
    r"""
    Scaled PDF of a power-law tail plus gaussian. 
    As a Numba vectorized function, it runs slightly faster than
    'out of the box' functions.

    Parameters
    ----------
    x
        The input data
    beta
        The point where the pdf changes from power-law to Gaussian
    m
        The power of the power-law tail
    mu
        The amount to shift the distribution
    sigma
        The amount to scale the distribution
    area
        The number of counts in the distribution
    """

    return area * nb_crystal_ball_pdf(x, beta, m, mu, sigma)


@nb.njit(**kwd)
def nb_crystal_ball_scaled_cdf(x: np.ndarray, area: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
    r"""
    Scaled CDF for power-law tail plus gaussian. Used for extended binned fits. 
    As a Numba vectorized function, it runs slightly faster than
    'out of the box' functions.

    Parameters
    ----------
    x
        The input data
    beta
        The point where the cdf changes from power-law to Gaussian
    m
        The power of the power-law tail
    mu
        The amount to shift the distribution
    sigma
        The amount to scale the distribution
    area
        The number of counts in the distribution
    """

    return area * nb_crystal_ball_cdf(x, beta, m, mu, sigma)


class crystal_ball_gen(pygama_continuous): 

    def _pdf(self, x: np.ndarray, beta: float, m: float) -> np.ndarray:
        x.flags.writeable = True
        return nb_crystal_ball_pdf(x, beta[0], m[0], 0, 1)
    def _cdf(self, x: np.ndarray, beta: float, m: float) -> np.ndarray:
        x.flags.writeable = True
        return nb_crystal_ball_cdf(x, beta[0], m[0], 0, 1)

    def get_pdf(self, x: np.ndarray, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return nb_crystal_ball_pdf(x, beta, m, mu, sigma)
    def get_cdf(self, x: np.ndarray, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return nb_crystal_ball_cdf(x, beta, m, mu, sigma)

    def norm_pdf(self, x: np.ndarray, x_lower: float, x_upper: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return self._norm_pdf(x, x_lower, x_upper, beta, m, mu, sigma)
    def norm_cdf(self, x: np.ndarray, x_lower: float, x_upper: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return self._norm_cdf(x, x_lower, x_upper, beta, m, mu, sigma)


    def pdf_ext(self, x: np.ndarray, area: float, x_lo: float, x_hi: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return nb_crystal_ball_scaled_cdf(np.array([x_hi]), area, beta, m, mu, sigma)[0]-nb_crystal_ball_scaled_cdf(np.array([x_lo]), area, beta, m, mu, sigma)[0], nb_crystal_ball_scaled_pdf(x, area, beta, m, mu, sigma)
    def cdf_ext(self, x: np.ndarray, area: float, beta: float, m: float, mu: float, sigma: float) -> np.ndarray:
        return nb_crystal_ball_scaled_cdf(x, area, beta, m, mu, sigma)

    def required_args(self) -> tuple[str, str, str, str]:
        return "beta", "m", "mu", "sigma"

crystal_ball = crystal_ball_gen(name = "crystal_ball")