from __future__ import (division, print_function, absolute_import)

import os
import numpy as np
from warnings import warn
import matplotlib
matplotlib.use('Agg') # Must be before importing matplotlib.pyplot
import matplotlib.pyplot as plt

from ValidationTest import ValidationTest, TestResult

from CalcStats import chisq, chisq_threshold
from helpers.CorrelationFunction import projected_correlation

catalog_output = 'catalog_wprp.txt'
validation_output = 'validation_wprp.txt'

class WprpTest(ValidationTest):
    """
    validation test class object to compute project 2-point correlation function wp(rp)
    """

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

        #set validation data information
        self._datafile = os.path.join(kwargs['base_data_dir'], kwargs['datafile'])
        self._dataname = kwargs['dataname']
        self._sm_cut = kwargs['sm_cut']
        self._rbins = np.logspace(*kwargs['rbins'])
        self._zmax = kwargs['zmax']
        self._njack = kwargs['njack']
        self._zlo = kwargs.get('zlo', -0.1)
        self._zhi = kwargs.get('zhi', 0.1)
        self._summary_thres = kwargs.get('summary_thres', 1.0)

    def run_validation_test(self, galaxy_catalog, galaxy_catalog_name, output_dir):
        """
        Load galaxy catalog and (re)calculate the stellar mass function.

        Parameters
        ----------
        galaxy_catalog : galaxy catalog reader object
            instance of a galaxy catalog reader

        galaxy_catalog_name : string
            name of mock galaxy catalog

        output_dir : string
            dictionary of output informaton

        Returns
        -------
        test_result : TestResult object
        """

        #make sure galaxy catalog has appropriate quantities
        required_quantities = ('stellar_mass', 'positionX', 'positionY', 'positionZ', 'velocityZ')

        if not all(q in galaxy_catalog.quantities for q in required_quantities):
            #raise an informative warning
            msg = 'galaxy catalog does not have all the required quantities {}, skipping the rest of the validation test.'.format(', '.join(required_quantities))
            warn(msg)
            return TestResult(skipped=True)

        #continue with the test
        gc = galaxy_catalog

        try:
            h = gc.cosmology.H0.value/100.0
        except AttributeError:
            h = 0.702
            msg = 'Make sure `cosmology` and `redshift` properties are set. Using default value h=0.702...'
            warn(msg)

        # convert arguments
        sm_cut = self._sm_cut/(h*h)
        rbins = self._rbins/h
        zmax = self._zmax/h
        njack = self._njack

        # load catalog
        gc_filter = {'zlo':self._zlo, 'zhi':self._zhi}
        flag = (gc.get_quantities("stellar_mass", gc_filter) >= sm_cut)
        x = gc.get_quantities("positionX", gc_filter)
        flag &= np.isfinite(x)

        x = x[flag]
        y = gc.get_quantities("positionY", gc_filter)[flag]
        z = gc.get_quantities("positionZ", gc_filter)[flag]
        vz = gc.get_quantities("velocityZ", gc_filter)[flag]

        vz /= (100.0*h)
        z += vz
        del vz

        # calc wp(rp)
        points = np.remainder(np.vstack((x,y,z)).T, gc.box_size)
        wp, wp_cov = projected_correlation(points, rbins, zmax, gc.box_size, njack)
        rp = np.sqrt(rbins[1:]*rbins[:-1])
        wp_err = np.sqrt(np.diag(wp_cov))
        save_wprp(os.path.join(output_dir, catalog_output), rp, wp, wp_err)

        rp_data, wp_data, wp_cov_data, wp_err_data = load_wprp_data(self._datafile)
        save_wprp(os.path.join(output_dir, validation_output), rp_data, wp_data, wp_err_data)

        with WprpPlot(os.path.join(output_dir, 'wprp.png'), sm_cut=sm_cut) as plot:
            plot.add_line(rp, wp, wp_err, galaxy_catalog_name)
            plot.add_points(rp_data, wp_data, wp_err_data, self._dataname, color='r', marker='s')

        chisq_value = chisq(wp - wp_data, wp_cov + wp_cov_data)
        chisq_thres_value = chisq_threshold(len(wp))
        success = (chisq_value < chisq_thres_value)
        summary = 'chi^2 = {} {} {}'.format(chisq_value, '<' if success else '>=', chisq_thres_value)

        return TestResult(chisq_value, summary, success)


class WprpPlot():
    def __init__(self, savefig, **kwargs):
        self.savefig = savefig
        self.kwargs = kwargs

    def __enter__(self):
        self.fig, self.ax = plt.subplots()
        return self

    def __exit__(self, *exc_args):
        self.ax.set_xscale('log')
        self.ax.set_yscale('linear')
        self.ax.set_xlim(0.1, 50.0)
        #self.ax.set_ylim(1.0, 3.0e3)
        self.ax.set_xlabel(r'$r_p \; {\rm [Mpc]}$')
        self.ax.set_ylabel(r'$r_p \, w_p(r_p) \; {\rm [Mpc]}$')
        self.ax.set_title(r'Projected correlation function ($M_* > {0:.2E} \, {{\rm M}}_\odot$)'.format(self.kwargs['sm_cut']))
        self.ax.legend(loc='upper left', frameon=False, fontsize='small', ncol=2)
        self.fig.tight_layout()
        self.fig.savefig(self.savefig)
        plt.close(self.fig)

    def add_line(self, rp, wp, wp_err, label, **kwargs):
        l = self.ax.loglog(rp, rp*wp, label=label, lw=1.5, **kwargs)[0]
        self.ax.fill_between(rp, rp*(wp+wp_err), rp*(wp-wp_err), alpha=0.15, color=l.get_color(), lw=0)

    def add_points(self, rp, wp, wp_err, label, **kwargs):
        self.ax.errorbar(rp, rp*wp, rp*wp_err, label=label, ls='', **kwargs)[0]


def save_wprp(output_file, rp, wp, wp_err):
    np.savetxt(output_file, np.vstack((rp, wp, wp_err)).T, header='rp wp wp_err')


def load_wprp(filename):
    return np.loadtxt(filename, unpack=True)


def load_wprp_data(filename):
    raw_data = np.loadtxt(filename)
    rp = raw_data[:,0]
    wp = raw_data[:,1]
    wp_cov = raw_data[:,2:]
    wp_err = np.sqrt(np.diag(wp_cov))
    return rp, wp, wp_cov, wp_err


def plot_summary(output_file, catalog_list, validation_kwargs):
    """
    make summary plot for validation test

    Parameters
    ----------
    output_file: string
        filename for summary plot

    catalog_list: list of tuple
        list of (catalog, catalog_output_dir) used for each catalog comparison

    validation_kwargs : dict
        keyword arguments used in the validation
    """
    colors= matplotlib.cm.get_cmap('nipy_spectral')(np.linspace(0, 1, len(catalog_list)+1)[:-1])

    sm_cut = validation_kwargs['sm_cut']/(0.702**2.0)
    with WprpPlot(output_file, sm_cut=sm_cut) as plot:
        for color, (catalog, catalog_output_dir) in zip(colors, catalog_list):
            rp, wp, wp_err = load_wprp(os.path.join(catalog_output_dir, catalog_output))
            plot.add_line(rp, wp, wp_err, catalog, color=color)

        rp, wp, wp_cov, wp_err = load_wprp_data(os.path.join(validation_kwargs['base_data_dir'], validation_kwargs['datafile']))
        plot.add_points(rp, wp, wp_err, validation_kwargs['dataname'], color='r', marker='s')


