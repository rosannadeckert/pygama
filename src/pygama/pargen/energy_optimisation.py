"""
This module contains the functions for performing the energy optimisation.
This happens in 2 steps, firstly a grid search is performed on each peak
separately using the optimiser, then the resulting grids are interpolated
to provide the best energy resolution at Qbb
"""

import json
import logging

import lgdo.lh5 as lh5
import matplotlib.pyplot as plt
import numpy as np

import pygama.math.distributions as pgd
import pygama.math.histogram as pgh
import pygama.pargen.energy_cal as pgc
from pygama.pargen.data_cleaning import find_pulser_properties, generate_cuts, get_keys
from pygama.pargen.dsp_optimize import run_one_dsp
from pygama.pargen.utils import convert_to_minuit, get_wf_indexes, return_nans

log = logging.getLogger(__name__)
sto = lh5.LH5Store()


def event_selection(
    raw_files,
    lh5_path,
    dsp_config,
    db_dict,
    peaks_kev,
    peak_idxs,
    kev_widths,
    cut_parameters=None,
    pulser_mask=None,
    energy_parameter="trapTmax",
    n_events=10000,
    threshold=1000,
    initial_energy="daqenergy",
    check_pulser=True,
):
    """
    Function for selecting events in peaks using raw files,
    to do this it uses the daqenergy to get a first rough selection
    then runs 1 dsp to get a more accurate energy estimate and apply cuts
    returns the indexes of the final events and the peak to which each index corresponds
    """

    if not isinstance(peak_idxs, list):
        peak_idxs = [peak_idxs]
    if not isinstance(kev_widths, list):
        kev_widths = [kev_widths]

    if lh5_path[-1] != "/":
        lh5_path += "/"

    raw_fields = [
        field.replace(lh5_path, "") for field in lh5.ls(raw_files[0], lh5_path)
    ]
    initial_fields = get_keys(raw_fields, [initial_energy])
    initial_fields += ["timestamp"]

    df = lh5.read_as(lh5_path, raw_files, "pd", field_mask=initial_fields)
    df["initial_energy"] = df.eval(initial_energy)

    if pulser_mask is None and check_pulser is True:
        pulser_props = find_pulser_properties(df, energy="initial_energy")
        if len(pulser_props) > 0:
            final_mask = None
            for entry in pulser_props:
                e_cut = (df.initial_energy.values < entry[0] + entry[1]) & (
                    df.initial_energy.values > entry[0] - entry[1]
                )
                if final_mask is None:
                    final_mask = e_cut
                else:
                    final_mask = final_mask | e_cut
            ids = final_mask
            log.debug(f"pulser found: {pulser_props}")
        else:
            log.debug("no_pulser")
            ids = np.zeros(len(df.initial_energy.values), dtype=bool)
        # Get events around peak using raw file values
    elif pulser_mask is not None:
        ids = pulser_mask
    else:
        ids = np.zeros(len(df.initial_energy.values), dtype=bool)

    initial_mask = (df["initial_energy"] > threshold) & (~ids)
    rough_energy = np.array(df["initial_energy"])[initial_mask]
    initial_idxs = np.where(initial_mask)[0]

    guess_kev = 2620 / np.nanpercentile(rough_energy, 99)
    euc_min = threshold / guess_kev * 0.6
    euc_max = 2620 / guess_kev * 1.1
    deuc = 1  # / guess_kev
    hist, bins, var = pgh.get_hist(rough_energy, range=(euc_min, euc_max), dx=deuc)
    detected_peaks_locs, detected_peaks_kev, roughpars = pgc.hpge_find_E_peaks(
        hist,
        bins,
        var,
        np.array([238.632, 583.191, 727.330, 860.564, 1620.5, 2103.53, 2614.553]),
    )
    log.debug(f"detected {detected_peaks_kev} keV peaks at {detected_peaks_locs}")

    masks = []
    for peak_idx in peak_idxs:
        peak = peaks_kev[peak_idx]
        kev_width = kev_widths[peak_idx]
        try:
            if peak not in detected_peaks_kev:
                raise ValueError
            detected_peak_idx = np.where(detected_peaks_kev == peak)[0]
            peak_loc = detected_peaks_locs[detected_peak_idx]
            log.info(f"{peak} peak found at {peak_loc}")
            rough_adc_to_kev = roughpars[0]
            e_lower_lim = peak_loc - (1.1 * kev_width[0]) / rough_adc_to_kev
            e_upper_lim = peak_loc + (1.1 * kev_width[1]) / rough_adc_to_kev
        except Exception:
            log.debug(f"{peak} peak not found attempting to use rough parameters")
            peak_loc = (peak - roughpars[1]) / roughpars[0]
            rough_adc_to_kev = roughpars[0]
            e_lower_lim = peak_loc - (1.5 * kev_width[0]) / rough_adc_to_kev
            e_upper_lim = peak_loc + (1.5 * kev_width[1]) / rough_adc_to_kev
        log.debug(f"lower_lim:{e_lower_lim}, upper_lim:{e_upper_lim}")
        e_mask = (rough_energy > e_lower_lim) & (rough_energy < e_upper_lim)
        e_idxs = initial_idxs[e_mask][: int(2.5 * n_events)]
        masks.append(e_idxs)
        log.debug(f"{len(e_idxs)} events found in energy range for {peak}")

    idx_list_lens = [len(masks[peak_idx]) for peak_idx in peak_idxs]

    sort_index = np.argsort(np.concatenate(masks))
    idx_list = get_wf_indexes(sort_index, idx_list_lens)
    idxs = np.array(sorted(np.concatenate(masks)))

    if len(idxs) == 0:
        raise ValueError("No events found in energy range")

    input_data = sto.read(f"{lh5_path}", raw_files, idx=idxs, n_rows=len(idxs))[0]

    if isinstance(dsp_config, str):
        with open(dsp_config) as r:
            dsp_config = json.load(r)

    dsp_config["outputs"] = get_keys(dsp_config["outputs"], cut_parameters) + [
        energy_parameter
    ]

    log.debug("Processing data")
    tb_data = run_one_dsp(input_data, dsp_config, db_dict=db_dict)

    ct_mask = np.full(len(tb_data), True, dtype=bool)
    if cut_parameters is not None:
        ct_mask = generate_cuts(tb_data, cut_parameters)
        log.debug("Cuts are calculated")

    final_events = []
    out_events = []
    for peak_idx in peak_idxs:
        peak = peaks_kev[peak_idx]
        kev_width = kev_widths[peak_idx]

        peak_ids = np.array(idx_list[peak_idx])
        peak_ct_mask = ct_mask[peak_ids]
        peak_ids = peak_ids[peak_ct_mask]

        energy = tb_data[energy_parameter].nda[peak_ids]

        hist, bins, var = pgh.get_hist(
            energy,
            range=(np.floor(np.nanmin(energy)), np.ceil(np.nanmax(energy))),
            dx=peak / (np.nanpercentile(energy, 50)),
        )
        peak_loc = pgh.get_bin_centers(bins)[np.nanargmax(hist)]

        mu, _, _ = pgc.hpge_fit_E_peak_tops(
            hist,
            bins,
            var,
            [peak_loc],
            n_to_fit=7,
        )[
            0
        ][0]

        if mu is None or np.isnan(mu):
            log.debug("Fit failed, using max guess")
            rough_adc_to_kev = peak / peak_loc
            e_lower_lim = peak_loc - (1.5 * kev_width[0]) / rough_adc_to_kev
            e_upper_lim = peak_loc + (1.5 * kev_width[1]) / rough_adc_to_kev
            hist, bins, var = pgh.get_hist(
                energy, range=(int(e_lower_lim), int(e_upper_lim)), dx=1
            )
            mu = pgh.get_bin_centers(bins)[np.nanargmax(hist)]

        updated_adc_to_kev = peak / mu
        e_lower_lim = mu - (kev_width[0]) / updated_adc_to_kev
        e_upper_lim = mu + (kev_width[1]) / updated_adc_to_kev
        log.info(f"lower lim is :{e_lower_lim}, upper lim is {e_upper_lim}")

        final_mask = (energy > e_lower_lim) & (energy < e_upper_lim)
        final_events.append(peak_ids[final_mask][:n_events])
        out_events.append(idxs[final_events[-1]])

        log.info(f"{len(peak_ids[final_mask][:n_events])} passed selections for {peak}")
        if len(peak_ids[final_mask]) < 0.5 * n_events:
            log.warning("Less than half number of specified events found")
        elif len(peak_ids[final_mask]) < 0.1 * n_events:
            log.error("Less than 10% number of specified events found")

    out_events = np.unique(np.concatenate(out_events))
    sort_index = np.argsort(np.concatenate(final_events))
    idx_list = get_wf_indexes(sort_index, [len(mask) for mask in final_events])
    return out_events, idx_list


def simple_guess(energy, func, fit_range=None, bin_width=1):
    """
    Simple guess for peak fitting
    """
    if fit_range is None:
        fit_range = (np.nanmin(energy), np.nanmax(energy))
    hist, bins, var = pgh.get_hist(energy, range=fit_range, dx=bin_width)

    if func == pgd.hpge_peak:
        bin_cs = (bins[1:] + bins[:-1]) / 2
        _, sigma, amp = pgh.get_gaussian_guess(hist, bins)
        i_0 = np.nanargmax(hist)
        mu = bin_cs[i_0]
        bg0 = np.mean(hist[-10:])
        step = np.mean(hist[:10]) - bg0
        htail = 1.0 / 5
        tau = 0.5 * sigma

        hstep = step / (bg0 + np.mean(hist[:10]))
        dx = np.diff(bins)[0]
        n_bins_range = int((4 * sigma) // dx)
        nsig = np.sum(hist[i_0 - n_bins_range : i_0 + n_bins_range])
        nbkg = np.sum(hist) - nsig
        parguess = {
            "n_sig": nsig,
            "mu": mu,
            "sigma": sigma,
            "htail": htail,
            "tau": tau,
            "n_bkg": nbkg,
            "hstep": hstep,
            "x_lo": fit_range[0],
            "x_hi": fit_range[1],
        }

    elif func == pgd.gauss_on_step:
        mu, sigma, amp = pgh.get_gaussian_guess(hist, bins)
        i_0 = np.argmax(hist)
        bg = np.mean(hist[-10:])
        step = bg - np.mean(hist[:10])
        hstep = step / (bg + np.mean(hist[:10]))
        dx = np.diff(bins)[0]
        n_bins_range = int((4 * sigma) // dx)
        nsig = np.sum(hist[i_0 - n_bins_range : i_0 + n_bins_range])
        nbkg = np.sum(hist) - nsig
        parguess = {
            "n_sig": nsig,
            "mu": mu,
            "sigma": sigma,
            "htail": htail,
            "tau": tau,
            "n_bkg": nbkg,
            "hstep": hstep,
            "x_lo": fit_range[0],
            "x_hi": fit_range[1],
        }
    else:
        log.error(f"simple_guess not implemented for {func.__name__}")
        return return_nans(func)

    return convert_to_minuit(parguess, func).values


def get_peak_fwhm_with_dt_corr(
    energies,
    alpha,
    dt,
    func,
    peak,
    kev_width,
    guess=None,
    kev=False,
    frac_max=0.5,
    allow_tail_drop=False,
    display=0,
):
    """
    Applies the drift time correction and fits the peak returns the fwhm, fwhm/max and associated errors,
    along with the number of signal events and the reduced chi square of the fit. Can return result in ADC or keV.
    """

    correction = np.multiply(
        np.multiply(alpha, dt, dtype="float64"), energies, dtype="float64"
    )
    ct_energy = np.add(correction, energies)

    bin_width = 1
    lower_bound = (np.nanmin(ct_energy) // bin_width) * bin_width
    upper_bound = ((np.nanmax(ct_energy) // bin_width) + 1) * bin_width
    hist, bins, var = pgh.get_hist(
        ct_energy, dx=bin_width, range=(lower_bound, upper_bound)
    )
    mu = bins[np.nanargmax(hist)]
    adc_to_kev = mu / peak
    # Making the window slightly smaller removes effects where as mu moves edge can be outside bin width
    lower_bound = mu - ((kev_width[0] - 2) * adc_to_kev)
    upper_bound = mu + ((kev_width[1] - 2) * adc_to_kev)
    win_idxs = (ct_energy > lower_bound) & (ct_energy < upper_bound)
    fit_range = (lower_bound, upper_bound)
    if peak > 1500:
        gof_range = (mu - (7 * adc_to_kev), mu + (7 * adc_to_kev))
    else:
        gof_range = (mu - (5 * adc_to_kev), mu + (5 * adc_to_kev))
    tol = None
    try:
        if display > 0:
            (
                energy_pars,
                energy_err,
                cov,
                chisqr,
                func,
                _,
                _,
                _,
            ) = pgc.unbinned_staged_energy_fit(
                ct_energy[win_idxs],
                func=func,
                fit_range=fit_range,
                guess_func=simple_guess,
                tol=tol,
                guess=guess,
                allow_tail_drop=allow_tail_drop,
                display=display,
            )
            plt.figure()
            xs = np.arange(lower_bound, upper_bound, bin_width)
            hist, bins, var = pgh.get_hist(
                ct_energy, dx=bin_width, range=(lower_bound, upper_bound)
            )
            plt.step((bins[1:] + bins[:-1]) / 2, hist)
            plt.plot(xs, func.get_pdf(xs, *energy_pars))
            plt.show()
        else:
            (
                energy_pars,
                energy_err,
                cov,
                chisqr,
                func,
                _,
                _,
                _,
            ) = pgc.unbinned_staged_energy_fit(
                ct_energy[win_idxs],
                func=func,
                gof_range=gof_range,
                fit_range=fit_range,
                guess_func=simple_guess,
                tol=tol,
                guess=guess,
                allow_tail_drop=allow_tail_drop,
            )

        fwhm = func.get_fwfm(energy_pars, frac_max)

        xs = np.arange(lower_bound, upper_bound, 0.1)
        y = func(xs, *energy_pars)[1]
        max_val = np.amax(y)

        fwhm_o_max = fwhm / max_val

        rng = np.random.default_rng(1)
        # generate set of bootstrapped parameters
        par_b = rng.multivariate_normal(energy_pars, cov, size=100)
        y_max = np.array([func(xs, *p)[1] for p in par_b])
        maxs = np.nanmax(y_max, axis=1)

        if func == pgd.hpge_peak and not (
            energy_pars["htail"] < 1e-6 and energy_err["htail"] < 1e-6
        ):
            y_b = np.zeros(len(par_b))
            for i, p in enumerate(par_b):
                try:
                    y_b[i] = func.get_fwfm(p, frac_max)
                except Exception:
                    y_b[i] = np.nan
            fwhm_err = np.nanstd(y_b, axis=0)
            fwhm_o_max_err = np.nanstd(y_b / maxs, axis=0)
        else:
            max_err = np.nanstd(maxs)
            fwhm_o_max_err = fwhm_o_max * np.sqrt(
                (np.array(fwhm_err) / np.array(fwhm)) ** 2
                + (np.array(max_err) / np.array(max_val)) ** 2
            )

        if display > 1:
            plt.figure()
            plt.step((bins[1:] + bins[:-1]) / 2, hist)
            for i in range(100):
                plt.plot(xs, y_max[i, :])
            plt.show()

        if display > 0:
            plt.figure()
            hist, bins, var = pgh.get_hist(
                ct_energy, dx=bin_width, range=(lower_bound, upper_bound)
            )
            plt.step((bins[1:] + bins[:-1]) / 2, hist)
            plt.plot(xs, y, color="orange")
            yerr_boot = np.nanstd(y_max, axis=0)
            plt.fill_between(
                xs, y - yerr_boot, y + yerr_boot, facecolor="C1", alpha=0.5
            )
            plt.show()

    except Exception:
        return np.nan, np.nan, np.nan, np.nan, (np.nan, np.nan), np.nan, np.nan, None

    if kev is True:
        fwhm *= peak / energy_pars["mu"]
        fwhm_err *= peak / energy_pars["mu"]

    return (
        fwhm,
        fwhm_o_max,
        fwhm_err,
        fwhm_o_max_err,
        chisqr,
        energy_pars["n_sig"],
        energy_err["n_sig"],
        energy_pars,
    )


def fom_fwhm_with_alpha_fit(
    tb_in, kwarg_dict, ctc_parameter, nsteps=29, idxs=None, frac_max=0.2, display=0
):
    """
    FOM for sweeping over ctc values to find the best value, returns the best found fwhm with its error,
    the corresponding alpha value and the number of events in the fitted peak, also the reduced chisquare of the
    """
    parameter = kwarg_dict["parameter"]
    func = kwarg_dict["func"]
    energies = tb_in[parameter].nda
    energies = energies.astype("float64")
    peak = kwarg_dict["peak"]
    kev_width = kwarg_dict["kev_width"]
    min_alpha = 0
    max_alpha = 3.50e-06
    alphas = np.linspace(min_alpha, max_alpha, nsteps, dtype="float64")
    try:
        dt = tb_in[ctc_parameter].nda
    except KeyError:
        dt = tb_in.eval(ctc_parameter, None, None)
    if idxs is not None:
        energies = energies[idxs]
        dt = dt[idxs]
    try:
        if np.isnan(energies).any():
            log.debug("nan in energies")
            raise RuntimeError
        if np.isnan(dt).any():
            log.debug("nan in dts")
            raise RuntimeError
        fwhms = np.array([])
        final_alphas = np.array([])
        fwhm_errs = np.array([])
        best_fwhm = np.inf
        for alpha in alphas:
            (
                _,
                fwhm_o_max,
                _,
                fwhm_o_max_err,
                _,
                _,
                _,
                fit_pars,
            ) = get_peak_fwhm_with_dt_corr(
                energies,
                alpha,
                dt,
                func,
                peak,
                kev_width,
                guess=None,
                frac_max=0.5,
                allow_tail_drop=False,
            )
            if not np.isnan(fwhm_o_max):
                fwhms = np.append(fwhms, fwhm_o_max)
                final_alphas = np.append(final_alphas, alpha)
                fwhm_errs = np.append(fwhm_errs, fwhm_o_max_err)
                if fwhms[-1] < best_fwhm:
                    best_fwhm = fwhms[-1]
            log.info(f"alpha: {alpha}, fwhm/max:{fwhm_o_max:.4f}+-{fwhm_o_max_err:.4f}")

        # Make sure fit isn't based on only a few points
        if len(fwhms) < nsteps * 0.2:
            log.debug("less than 20% fits successful")
            raise RuntimeError

        ids = (fwhm_errs < 2 * np.nanpercentile(fwhm_errs, 50)) & (fwhm_errs > 1e-10)
        # Fit alpha curve to get best alpha

        try:
            alphas = np.linspace(
                final_alphas[ids][0],
                final_alphas[ids][-1],
                nsteps * 20,
                dtype="float64",
            )
            alpha_fit, cov = np.polyfit(
                final_alphas[ids], fwhms[ids], w=1 / fwhm_errs[ids], deg=4, cov=True
            )
            fit_vals = np.polynomial.polynomial.polyval(alphas, alpha_fit[::-1])
            alpha = alphas[np.nanargmin(fit_vals)]

            rng = np.random.default_rng(1)
            alpha_pars_b = rng.multivariate_normal(alpha_fit, cov, size=1000)
            fits = np.array(
                [
                    np.polynomial.polynomial.polyval(alphas, pars[::-1])
                    for pars in alpha_pars_b
                ]
            )
            min_alphas = np.array([alphas[np.nanargmin(fit)] for fit in fits])
            alpha_err = np.nanstd(min_alphas)
            if display > 0:
                plt.figure()
                yerr_boot = np.std(fits, axis=0)
                plt.errorbar(final_alphas, fwhms, yerr=fwhm_errs, linestyle=" ")
                plt.plot(alphas, fit_vals)
                plt.fill_between(
                    alphas,
                    fit_vals - yerr_boot,
                    fit_vals + yerr_boot,
                    facecolor="C1",
                    alpha=0.5,
                )
                plt.show()

        except BaseException as be:
            log.debug("alpha fit failed")
            raise be

        if np.isnan(fit_vals).all():
            log.debug("alpha fit all nan")
            raise RuntimeError
        (
            final_fwhm,
            _,
            final_err,
            _,
            csqr,
            n_sig,
            n_sig_err,
            _,
        ) = get_peak_fwhm_with_dt_corr(
            energies,
            alpha,
            dt,
            func,
            peak,
            kev_width,
            guess=None,
            kev=True,
            frac_max=frac_max,
            allow_tail_drop=True,
            display=display,
        )
        if np.isnan(final_fwhm) or np.isnan(final_err):
            log.debug(f"final fit failed, alpha was {alpha}")
            raise RuntimeError
        return {
            "fwhm": final_fwhm,
            "fwhm_err": final_err,
            "alpha": alpha,
            "alpha_err": alpha_err,
            "chisquare": csqr,
            "n_sig": n_sig,
            "n_sig_err": n_sig_err,
        }
    except Exception:
        return {
            "fwhm": np.nan,
            "fwhm_err": np.nan,
            "alpha": 0,
            "alpha_err": np.nan,
            "chisquare": (np.nan, np.nan),
            "n_sig": np.nan,
            "n_sig_err": np.nan,
        }


def fom_fwhm_no_alpha_sweep(
    tb_in, kwarg_dict, ctc_param=None, alpha=0, idxs=None, display=0
):
    """
    FOM with no ctc sweep, used for optimising ftp.
    """
    parameter = kwarg_dict["parameter"]
    func = kwarg_dict["func"]
    energies = tb_in[parameter].nda
    energies = energies.astype("float64")
    peak = kwarg_dict["peak"]
    kev_width = kwarg_dict["kev_width"]
    alpha = kwarg_dict.get("alpha", alpha)
    if isinstance(alpha, dict):
        alpha = alpha[parameter]
    if "ctc_param" in kwarg_dict or ctc_param is not None:
        ctc_param = kwarg_dict.get("ctc_param", ctc_param)
        try:
            dt = tb_in[ctc_param].nda
        except KeyError:
            dt = tb_in.eval(ctc_param, None, None)
            dt = tb_in[ctc_param].nda
    else:
        dt = 0

    if idxs is not None:
        energies = energies[idxs]
        dt = dt[idxs]

    if np.isnan(energies).any():
        return {
            "fwhm": np.nan,
            "fwhm_o_max": np.nan,
            "fwhm_err": np.nan,
            "fwhm_o_max_err": np.nan,
            "chisquare": np.nan,
            "n_sig": np.nan,
            "n_sig_err": np.nan,
        }
    (
        fwhm,
        final_fwhm_o_max,
        fwhm_err,
        final_fwhm_o_max_err,
        csqr,
        n_sig,
        n_sig_err,
    ) = get_peak_fwhm_with_dt_corr(
        energies,
        alpha,
        dt,
        func,
        peak=peak,
        kev_width=kev_width,
        kev=True,
        display=display,
    )
    return {
        "fwhm": fwhm,
        "fwhm_o_max": final_fwhm_o_max,
        "fwhm_err": fwhm_err,
        "fwhm_o_max_err": final_fwhm_o_max_err,
        "chisquare": csqr,
        "n_sig": n_sig,
        "n_sig_err": n_sig_err,
    }


def fom_single_peak_alpha_sweep(data, kwarg_dict):
    idx_list = kwarg_dict["idx_list"]
    ctc_param = kwarg_dict["ctc_param"]
    peak_dicts = kwarg_dict["peak_dicts"]
    frac_max = kwarg_dict.get("frac_max", 0.2)
    out_dict = fom_fwhm_with_alpha_fit(
        data, peak_dicts[0], ctc_param, idxs=idx_list[0], frac_max=frac_max, display=0
    )
    return out_dict


def fom_interpolate_energy_res_with_single_peak_alpha_sweep(data, kwarg_dict):
    peaks = kwarg_dict["peaks_kev"]
    idx_list = kwarg_dict["idx_list"]
    ctc_param = kwarg_dict["ctc_param"]
    peak_dicts = kwarg_dict["peak_dicts"]
    interp_energy = kwarg_dict.get("interp_energy", {"Qbb": 2039})
    fwhm_func = kwarg_dict.get("fwhm_func", pgc.FWHMLinear)
    frac_max = kwarg_dict.get("frac_max", 0.2)

    out_dict = fom_fwhm_with_alpha_fit(
        data, peak_dicts[-1], ctc_param, idxs=idx_list[-1], frac_max=frac_max, display=0
    )
    alpha = out_dict["alpha"]
    log.info(alpha)
    fwhms = []
    fwhm_errs = []
    n_sig = []
    n_sig_err = []
    for i, _ in enumerate(peaks[:-1]):
        out_peak_dict = fom_fwhm_no_alpha_sweep(
            data,
            peak_dicts[i],
            ctc_param,
            alpha=alpha,
            idxs=idx_list[i],
            frac_max=frac_max,
            display=0,
        )
        fwhms.append(out_peak_dict["fwhm"])
        fwhm_errs.append(out_peak_dict["fwhm_err"])
        n_sig.append(out_peak_dict["n_sig"])
        n_sig_err.append(out_peak_dict["n_sig_err"])
    fwhms.append(out_dict["fwhm"])
    fwhm_errs.append(out_dict["fwhm_err"])
    n_sig.append(out_dict["n_sig"])
    n_sig_err.append(out_dict["n_sig_err"])
    log.info(f"fwhms are {fwhms}keV +- {fwhm_errs}")

    nan_mask = np.isnan(fwhms) | (fwhms < 0)
    if len(fwhms[~nan_mask]) < 2:
        return np.nan, np.nan, np.nan
    else:
        results = pgc.HPGeCalibration.fit_energy_res_curve(
            fwhm_func, peaks[~nan_mask], fwhms[~nan_mask], fwhm_errs[~nan_mask]
        )
        results = pgc.HPGeCalibration.interpolate_energy_res(
            fwhm_func, peaks[~nan_mask], results, interp_energy
        )
        interp_res = results[f"{list(interp_energy)[0]}_fwhm_in_kev"]
        interp_res_err = results[f"{list(interp_energy)[0]}_fwhm_err_in_kev"]

        if nan_mask[-1] is True or nan_mask[-2] is True:
            interp_res_err = np.nan
        if interp_res_err / interp_res > 0.1:
            interp_res_err = np.nan

    log.info(f"{list(interp_energy)[0]} fwhm is {interp_res} keV +- {interp_res_err}")

    return {
        f"{list(interp_energy)[0]}_fwhm": interp_res,
        f"{list(interp_energy)[0]}_fwhm_err": interp_res_err,
        "alpha": alpha,
        "peaks": peaks.tolist(),
        "fwhms": fwhms,
        "fwhm_errs": fwhm_errs,
        "n_sig": n_sig,
        "n_sig_err": n_sig_err,
    }
