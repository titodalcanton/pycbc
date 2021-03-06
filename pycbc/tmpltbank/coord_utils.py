# Copyright (C) 2013 Ian W. Harry
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

from __future__ import division
import logging
import numpy
import os.path
from pycbc.tmpltbank.lambda_mapping import get_chirp_params
from pycbc import pnutils
from pycbc.tmpltbank.em_progenitors import generate_em_constraint_data, load_ns_sequence, min_eta_for_em_bright

def estimate_mass_range(numPoints, massRangeParams, metricParams, fUpper,\
                        covary=True):
    """
    This function will generate a large set of points with random masses and
    spins (using pycbc.tmpltbank.get_random_mass) and translate these points
    into the xi_i coordinate system for the given upper frequency cutoff.

    Parameters
    ----------
    numPoints : int
        Number of systems to simulate
    massRangeParams : massRangeParameters instance
        Instance holding all the details of mass ranges and spin ranges.
    metricParams : metricParameters instance
        Structure holding all the options for construction of the metric
        and the eigenvalues, eigenvectors and covariance matrix
        needed to manipulate the space.
    fUpper : float
        The value of fUpper to use when getting the mu coordinates from the
        lambda coordinates. This must be a key in metricParams.evals and
        metricParams.evecs (ie. we must know how to do the transformation for
        the given value of fUpper). It also must be a key in
        metricParams.evecsCV if covary=True.
    covary : boolean, optional (default = True)
        If this is given then evecsCV will be used to rotate from the Cartesian
        coordinate system into the principal coordinate direction (xi_i). If
        not given then points in the original Cartesian coordinates are
        returned.


    Returns
    -------
    xis : numpy.array
        A list of the positions of each point in the xi_i coordinate system.
    """
    valsF = get_random_mass(numPoints, massRangeParams)
    mass = valsF[0]
    eta = valsF[1]
    beta = valsF[2]
    sigma = valsF[3]
    gamma = valsF[4]
    chis = 0.5*(valsF[5] + valsF[6])
    if covary:
        lambdas = get_cov_params(mass, eta, beta, sigma, gamma, chis, \
                                 metricParams, fUpper)
    else:
        lambdas = get_conv_params(mass, eta, beta, sigma, gamma, chis, \
                                  metricParams, fUpper)

    return numpy.array(lambdas)

def get_random_mass_point_particles(numPoints, massRangeParams):
    """
    This function will generate a large set of points within the chosen mass
    and spin space. It will also return the corresponding PN spin coefficients
    for ease of use later (though these may be removed at some future point).

    Parameters
    ----------
    numPoints : int
        Number of systems to simulate
    massRangeParams : massRangeParameters instance
        Instance holding all the details of mass ranges and spin ranges.

    Returns
    --------
    mass : numpy.array
        List of the total masses.
    eta : numpy.array
        List of the symmetric mass ratios
    beta : numpy.array
        List of the 1.5PN beta spin coefficients
    sigma : numpy.array
        List of the 2PN sigma spin coefficients
    gamma : numpy.array
        List of the 2.5PN gamma spin coefficients
    spin1z : numpy.array
        List of the spin on the heavier body. NOTE: Body 1 is **always** the
        heavier body to remove mass,eta -> m1,m2 degeneracy
    spin2z : numpy.array
        List of the spin on the smaller body. NOTE: Body 2 is **always** the
        smaller body to remove mass,eta -> m1,m2 degeneracy
    mass1 : numpy.array
        List of the mass of the heavier body. NOTE: Body 1 is **always** the
        heavier body to remove mass,eta -> m1,m2 degeneracy
    mass2 : numpy.array
        List of the mass of the smaller body. NOTE: Body 2 is **always** the
        smaller body to remove mass,eta -> m1,m2 degeneracy
    """

    # WARNING: We expect mass1 > mass2 ALWAYS

    # First we choose the total masses from a unifrom distribution in mass
    # to the -5/3. power.
    mass = numpy.random.random(numPoints) * \
           (massRangeParams.minTotMass**(-5./3.) \
            - massRangeParams.maxTotMass**(-5./3.)) \
           + massRangeParams.maxTotMass**(-5./3.)
    mass = mass**(-3./5.)

    # Next we choose the mass ratios, this will take different limits based on
    # the value of total mass
    maxmass2 = numpy.minimum(mass/2., massRangeParams.maxMass2)
    minmass1 = numpy.maximum(massRangeParams.minMass1, mass/2.)
    mineta = numpy.maximum(massRangeParams.minCompMass \
                            * (mass-massRangeParams.minCompMass)/(mass*mass), \
                           massRangeParams.maxCompMass \
                            * (mass-massRangeParams.maxCompMass)/(mass*mass))
    # Note that mineta is a numpy.array because mineta depends on the total
    # mass. Therefore this is not precomputed in the massRangeParams instance
    if massRangeParams.minEta:
        mineta = numpy.maximum(massRangeParams.minEta, mineta)
    # Eta also restricted by chirp mass restrictions
    if massRangeParams.min_chirp_mass:
        eta_val_at_min_chirp = massRangeParams.min_chirp_mass / mass
        eta_val_at_min_chirp = eta_val_at_min_chirp**(5./3.)
        mineta = numpy.maximum(mineta, eta_val_at_min_chirp)

    maxeta = numpy.minimum(massRangeParams.maxEta, maxmass2 \
                             * (mass - maxmass2) / (mass*mass))
    maxeta = numpy.minimum(maxeta, minmass1 \
                             * (mass - minmass1) / (mass*mass))
    # max eta also affected by chirp mass restrictions
    if massRangeParams.max_chirp_mass:
        eta_val_at_max_chirp = massRangeParams.max_chirp_mass / mass
        eta_val_at_max_chirp = eta_val_at_max_chirp**(5./3.)
        maxeta = numpy.minimum(maxeta, eta_val_at_max_chirp)

    if (maxeta < mineta).any():
        errMsg = "ERROR: Maximum eta is smaller than minimum eta!!"
        raise ValueError(errMsg)
    eta = numpy.random.random(numPoints) * (maxeta - mineta) + mineta

    # Also calculate the component masses; mass1 > mass2
    diff = (mass*mass * (1-4*eta))**0.5
    mass1 = (mass + diff)/2.
    mass2 = (mass - diff)/2.
    # Check the masses are where we want them to be (allowing some floating
    # point rounding error).
    if (mass1 > massRangeParams.maxMass1*1.001).any() \
          or (mass1 < massRangeParams.minMass1*0.999).any():
        errMsg = "Mass1 is not within the specified mass range."
        raise ValueError(errMsg)
    if (mass2 > massRangeParams.maxMass2*1.001).any() \
          or (mass2 < massRangeParams.minMass2*0.999).any():
        errMsg = "Mass2 is not within the specified mass range."
        raise ValueError(errMsg)

    # Next up is the spins. First check if we have non-zero spins
    if massRangeParams.maxNSSpinMag == 0 and massRangeParams.maxBHSpinMag == 0:
        spinspin = numpy.zeros(numPoints,dtype=float)
        spin1z = numpy.zeros(numPoints,dtype=float)
        spin2z = numpy.zeros(numPoints,dtype=float)
        beta = numpy.zeros(numPoints,dtype=float)
        sigma = numpy.zeros(numPoints,dtype=float)
        gamma = numpy.zeros(numPoints,dtype=float)
        spin1z = numpy.zeros(numPoints,dtype=float)
        spin2z = numpy.zeros(numPoints,dtype=float)
    elif massRangeParams.nsbhFlag:
        # Spin 1 first
        mspin = numpy.zeros(len(mass1))
        mspin += massRangeParams.maxBHSpinMag
        spin1z = (2*numpy.random.random(numPoints) - 1) * mspin
        # Then spin2
        mspin = numpy.zeros(len(mass2))
        mspin += massRangeParams.maxNSSpinMag
        spin2z = (2*numpy.random.random(numPoints) - 1) * mspin
        # And compute the PN components that come out of this
        beta, sigma, gamma, chiS = pnutils.get_beta_sigma_from_aligned_spins(
            eta, spin1z, spin2z)
    else:        
        boundary_mass = massRangeParams.ns_bh_boundary_mass
        # Spin 1 first
        mspin = numpy.zeros(len(mass1))
        mspin += massRangeParams.maxNSSpinMag
        mspin[mass1 > boundary_mass] = massRangeParams.maxBHSpinMag
        spin1z = (2*numpy.random.random(numPoints) - 1) * mspin
        # Then spin 2
        mspin = numpy.zeros(len(mass2))
        mspin += massRangeParams.maxNSSpinMag
        mspin[mass2 > boundary_mass] = massRangeParams.maxBHSpinMag
        spin2z = (2*numpy.random.random(numPoints) - 1) * mspin
        # And compute the PN components that come out of this
        beta, sigma, gamma, chiS = pnutils.get_beta_sigma_from_aligned_spins(
            eta, spin1z, spin2z)

    return mass,eta,beta,sigma,gamma,spin1z,spin2z,mass1,mass2

def get_random_mass(numPoints, massRangeParams):
    """
    This function will generate a large set of points within the chosen mass
    and spin space, and with the desired minimum remnant disk mass (this applies
    to NS-BH systems only). It will also return the corresponding PN spin
    coefficients for ease of use later (though these may be removed at some
    future point).

    Parameters
    ----------
    numPoints : int
        Number of systems to simulate
    massRangeParams : massRangeParameters instance
        Instance holding all the details of mass ranges and spin ranges.

    Returns
    --------
    mass : numpy.array
        List of the total masses.
    eta : numpy.array
        List of the symmetric mass ratios
    beta : numpy.array
        List of the 1.5PN beta spin coefficients
    sigma : numpy.array
        List of the 2PN sigma spin coefficients
    gamma : numpy.array
        List of the 2.5PN gamma spin coefficients
    spin1z : numpy.array
        List of the spin on the heavier body. NOTE: Body 1 is **always** the
        heavier body to remove mass,eta -> m1,m2 degeneracy
    spin2z : numpy.array
        List of the spin on the smaller body. NOTE: Body 2 is **always** the
        smaller body to remove mass,eta -> m1,m2 degeneracy
    """

    # WARNING: We expect mass1 > mass2 ALWAYS

    # Check if EM contraints are required, i.e. if the systems must produce
    # a minimum remnant disk mass.  If this is not the case, proceed treating
    # the systems as point particle binaries
    if massRangeParams.remnant_mass_threshold is None:
        mass, eta, beta, sigma, gamma, spin1z, spin2z, mass1, mass2 = \
        get_random_mass_point_particles(numPoints, massRangeParams)
    # otherwise, load EOS dependent data, generate the EM constraint
    # (i.e. compute the minimum symmetric mass ratio needed to
    # generate a given remnant disk mass as a function of the NS
    # mass and the BH spin along z) and then proceed by accepting
    # only systems that can yield (at least) the desired remnant
    # disk mass and that pass the mass and spin range cuts.
    else:
        ns_sequence, max_ns_g_mass = load_ns_sequence(massRangeParams.ns_eos)

        # Generate EM constraint surface: minumum eta as a function of BH spin
        # and NS mass required to produce an EM counterpart
        if not os.path.isfile('constraint_em_bright.npz'):
            logging.info("""constraint_em_bright.npz not found.
                        Generating the constraint surface for EM bright binaries
                        in the physical parameter space.  One day, this will be
                        made faster, for now be patient and wait a few minutes!""")
            generate_em_constraint_data(massRangeParams.minMass2, massRangeParams.maxMass2, massRangeParams.delta_ns_mass, \
                                        -1.0, massRangeParams.maxBHSpinMag, massRangeParams.delta_bh_spin, \
                                        massRangeParams.ns_eos, massRangeParams.remnant_mass_threshold, 0.0)
        constraint_datafile = numpy.load('constraint_em_bright.npz')
        mNS_pts = constraint_datafile['mNS_pts']
        bh_spin_z_pts = constraint_datafile['sBH_pts']
        eta_mins = constraint_datafile['eta_mins']

        # Empty arrays to store points that pass all cuts
        massOut = []
        etaOut = []
        betaOut = []
        sigmaOut = []
        gammaOut = []
        spin1zOut = []
        spin2zOut = []

        # As the EM cut can remove several randomly generated
        # binaries, track the number of accepted points that pass
        # all cuts and stop only once enough of them are generated
        numPointsFound = 0
        while numPointsFound < numPoints:
            # Generate the random points within the required mass
            # and spin cuts
            mass, eta, beta, sigma, gamma, spin1z, spin2z, mass1, mass2 = \
            get_random_mass_point_particles(numPoints-numPointsFound, massRangeParams)

            # Now proceed with cutting out EM dim systems
            # Logical mask to clean up points by removing EM dim binaries
            mask = numpy.ones(len(mass1), dtype=bool)
            # Commpute the minimum eta to generate a counterpart
            min_eta_em = min_eta_for_em_bright(spin1z, mass2, mNS_pts, bh_spin_z_pts, eta_mins)
            # Remove a point if:
            # 1) eta is smaller than the eta threshold required to have a counterpart;
            # 2) the primary is a BH (mass1 >= ns_bh_boundary_mass);
            # 3) the secondary mass does not exceed the maximum NS mass
            # allowed by the EOS (if the user runs with --use-eos-max-ns-mass
            # this last condition will always be true, otherwise the user is
            # implicitly asking to keep binaries in which the secondary may be
            # a BH).
            mask[(mass1 >= massRangeParams.ns_bh_boundary_mass) & (mass2 <= max_ns_g_mass) & (eta < min_eta_em)] = False
            # Keep only binaries that can produce an EM counterpart and add them to
            # the pile of accpeted points to output
            massOut   = numpy.concatenate((massOut,mass[mask]))
            etaOut    = numpy.concatenate((etaOut,eta[mask]))
            betaOut   = numpy.concatenate((betaOut,beta[mask]))
            sigmaOut  = numpy.concatenate((sigmaOut,sigma[mask]))
            gammaOut  = numpy.concatenate((gammaOut,gamma[mask]))
            spin1zOut = numpy.concatenate((spin1zOut,spin1z[mask]))
            spin2zOut = numpy.concatenate((spin2zOut,spin2z[mask]))

            # Number of points that survived all cuts
            numPointsFound = len(massOut)

        # Ready to go
        mass = massOut
        eta = etaOut
        beta = betaOut
        sigma = sigmaOut
        gamma = gammaOut
        spin1z = spin1zOut
        spin2z = spin2zOut

    return mass,eta,beta,sigma,gamma,spin1z,spin2z

def get_cov_params(totmass, eta, beta, sigma, gamma, chis, metricParams, \
                   fUpper):
    """
    Function to convert between masses and spins and locations in the xi
    parameter space. Xi = Cartesian metric and rotated to principal components.

    Parameters
    -----------
    totmass : float or numpy.array
        Total mass(es) of the system(s)
    eta : float or numpy.array
        Symmetric mass ratio(s) of the system(s)
    beta : float or numpy.array
        1.5PN spin coefficient(s) of the system(s)
    sigma: float or numpy.array
        2PN spin coefficient(s) of the system(s)
    gamma : float or numpy.array
        2.5PN spin coefficient(s) of the system(s)
    chis : float or numpy.array
        0.5 * (spin1z + spin2z) for the system(s)
    metricParams : metricParameters instance
        Structure holding all the options for construction of the metric
        and the eigenvalues, eigenvectors and covariance matrix
        needed to manipulate the space.
    fUpper : float
        The value of fUpper to use when getting the mu coordinates from the
        lambda coordinates. This must be a key in metricParams.evals,
        metricParams.evecs and metricParams.evecsCV
        (ie. we must know how to do the transformation for
        the given value of fUpper)

    Returns
    --------
    xis : list of floats or numpy.arrays
        Position of the system(s) in the xi coordinate system
    """

    # Do this by doing masses - > lambdas -> mus
    mus = get_conv_params(totmass, eta, beta, sigma, gamma, chis, \
                          metricParams, fUpper)
    # and then mus -> xis
    xis = get_covaried_params(mus, metricParams.evecsCV[fUpper])
    return xis

def get_conv_params(totmass, eta, beta, sigma, gamma, chis, metricParams, \
                    fUpper):
    """
    Function to convert between masses and spins and locations in the mu
    parameter space. Mu = Cartesian metric, but not principal components.

    Parameters
    -----------
    totmass : float or numpy.array
        Total mass(es) of the system(s)
    eta : float or numpy.array
        Symmetric mass ratio(s) of the system(s)
    beta : float or numpy.array
        1.5PN spin coefficient(s) of the system(s)
    sigma: float or numpy.array
        2PN spin coefficient(s) of the system(s)
    gamma : float or numpy.array
        2.5PN spin coefficient(s) of the system(s)
    chis : float or numpy.array
        0.5 * (spin1z + spin2z) for the system(s)
    metricParams : metricParameters instance
        Structure holding all the options for construction of the metric
        and the eigenvalues, eigenvectors and covariance matrix
        needed to manipulate the space.
    fUpper : float
        The value of fUpper to use when getting the mu coordinates from the
        lambda coordinates. This must be a key in metricParams.evals and
        metricParams.evecs (ie. we must know how to do the transformation for
        the given value of fUpper)

    Returns
    --------
    mus : list of floats or numpy.arrays
        Position of the system(s) in the mu coordinate system
    """

    # Do this by masses -> lambdas
    lambdas = get_chirp_params(totmass, eta, beta, sigma, gamma, chis, \
                               metricParams.f0, metricParams.pnOrder)
    # and lambdas -> mus
    mus = get_mu_params(lambdas, metricParams, fUpper)
    return mus

def get_mu_params(lambdas, metricParams, fUpper):
    """
    Function to rotate from the lambda coefficients into position in the mu
    coordinate system. Mu = Cartesian metric, but not principal components.

    Parameters
    -----------
    lambdas : list of floats or numpy.arrays
        Position of the system(s) in the lambda coefficients
    metricParams : metricParameters instance
        Structure holding all the options for construction of the metric
        and the eigenvalues, eigenvectors and covariance matrix
        needed to manipulate the space.
    fUpper : float
        The value of fUpper to use when getting the mu coordinates from the
        lambda coordinates. This must be a key in metricParams.evals and
        metricParams.evecs (ie. we must know how to do the transformation for
        the given value of fUpper)

    Returns
    --------
    mus : list of floats or numpy.arrays
        Position of the system(s) in the mu coordinate system
    """
    evecs = metricParams.evecs[fUpper]
    evals = metricParams.evals[fUpper]

    mus = []
    for i in xrange(len(evals)):
        mus.append(rotate_vector(evecs,lambdas,numpy.sqrt(evals[i]),i))
    return mus

def get_covaried_params(mus, evecsCV):
    """
    Function to rotate from position(s) in the mu_i coordinate system into the
    position(s) in the xi_i coordinate system

    Parameters
    -----------
    mus : list of floats or numpy.arrays
        Position of the system(s) in the mu coordinate system
    evecsCV : numpy.matrix
        This matrix is used to perform the rotation to the xi_i
        coordinate system.

    Returns
    --------
    xis : list of floats or numpy.arrays
        Position of the system(s) in the xi coordinate system
    """
    xis = []
    for i in xrange(len(evecsCV)):
        xis.append(rotate_vector(evecsCV,mus,1.,i))
    return xis

def rotate_vector(evecs, old_vector, rescale_factor, index):
    """
    Function to find the position of the system(s) in one of the xi_i or mu_i
    directions.

    Parameters
    -----------
    evecs : numpy.matrix
        Matrix of the eigenvectors of the metric in lambda_i coordinates. Used
        to rotate to a Cartesian coordinate system.
    old_vector : list of floats or numpy.arrays
        The position of the system(s) in the original coordinates
    rescale_factor : float
        Scaling factor to apply to resulting position(s)
    index : int
        The index of the final coordinate system that is being computed. Ie.
        if we are going from mu_i -> xi_j, this will give j.

    Returns
    --------
    positions : float or numpy.array
        Position of the point(s) in the resulting coordinate.
    """
    temp = 0
    for i in xrange(len(evecs)):
        temp += evecs[i,index] * old_vector[i]
    temp *= rescale_factor
    return temp

def get_point_distance(point1, point2, metricParams, fUpper):
    """
    Function to calculate the mismatch between two points, supplied in terms
    of the masses and spins, using the xi_i parameter space metric to
    approximate the mismatch of the two points. Can also take one of the points
    as an array of points and return an array of mismatches (but only one can
    be an array!)

    point1 : List of floats or numpy.arrays
        point1[0] contains the mass(es) of the heaviest body(ies).
        point1[1] contains the mass(es) of the smallest body(ies).
        point1[2] contains the spin(es) of the heaviest body(ies).
        point1[3] contains the spin(es) of the smallest body(ies).
    point2 : List of floats
        point2[0] contains the mass of the heaviest body.
        point2[1] contains the mass of the smallest body.
        point2[2] contains the spin of the heaviest body.
        point2[3] contains the spin of the smallest body.
    metricParams : metricParameters instance
        Structure holding all the options for construction of the metric
        and the eigenvalues, eigenvectors and covariance matrix
        needed to manipulate the space.
    fUpper : float
        The value of fUpper to use when getting the mu coordinates from the
        lambda coordinates. This must be a key in metricParams.evals,
        metricParams.evecs and metricParams.evecsCV
        (ie. we must know how to do the transformation for
        the given value of fUpper)

    Returns
    --------
    dist : float or numpy.array
        Distance between the point2 and all points in point1
    xis1 : List of floats or numpy.arrays
        Position of the input point1(s) in the xi_i parameter space
    xis2 : List of floats
        Position of the input point2 in the xi_i parameter space
    """
    aMass1 = point1[0]
    aMass2 = point1[1]
    aSpin1 = point1[2]
    aSpin2 = point1[3]
    try:
        leng = len(aMass1)
        aArray = True
    except:
        aArray = False

    bMass1 = point2[0]
    bMass2 = point2[1]
    bSpin1 = point2[2]
    bSpin2 = point2[3]
    bArray = False

    aTotMass = aMass1 + aMass2
    aEta = (aMass1 * aMass2) / (aTotMass * aTotMass)
    aCM = aTotMass * aEta**(3./5.)

    bTotMass = bMass1 + bMass2
    bEta = (bMass1 * bMass2) / (bTotMass * bTotMass)
    bCM = bTotMass * bEta**(3./5.)

    abeta, asigma, agamma, achis = pnutils.get_beta_sigma_from_aligned_spins(
        aEta, aSpin1, aSpin2)
    bbeta, bsigma, bgamma, bchis = pnutils.get_beta_sigma_from_aligned_spins(
        bEta, bSpin1, bSpin2)

    aXis = get_cov_params(aTotMass, aEta, abeta, asigma, agamma, achis, \
                          metricParams, fUpper)

    bXis = get_cov_params(bTotMass, bEta, bbeta, bsigma, bgamma, bchis, \
                          metricParams, fUpper)

    dist = (aXis[0] - bXis[0])**2
    for i in xrange(1,len(aXis)):
        dist += (aXis[i] - bXis[i])**2

    return dist, aXis, bXis

def calc_point_dist(vsA, entryA):
    """
    This function is used to determine the distance between two points.

    Parameters
    ----------
    vsA : list or numpy.array or similar
        An array of point 1's position in the \chi_i coordinate system
    entryA : list or numpy.array or similar
        An array of point 2's position in the \chi_i coordinate system
    MMdistA : float
        The minimal mismatch allowed between the points

    Returns
    --------
    val : float
        The metric distance between the two points.
    """
    chi_diffs = vsA - entryA
    val = ((chi_diffs)*(chi_diffs)).sum()
    return val 

def test_point_dist(point_1_chis, point_2_chis, distance_threshold):
    """
    This function tests if the difference between two points in the chi
    parameter space is less than a distance threshold. Returns True if it is
    and False if it is not.   

    Parameters
    ----------
    point_1_chis : numpy.array
        An array of point 1's position in the \chi_i coordinate system
    point_2_chis : numpy.array
        An array of point 2's position in the \chi_i coordinate system
    distance_threshold : float
        The distance threshold to use.
    """
    return calc_point_dist(point_1_chis, point_2_chis) < distance_threshold


def calc_point_dist_vary(mus1, fUpper1, mus2, fUpper2, fMap, norm_map, MMdistA):
    """
    Function to determine if two points, with differing upper frequency cutoffs
    have a mismatch < MMdistA for *both* upper frequency cutoffs.

    Parameters
    ----------
    mus1 : List of numpy arrays
        mus1[i] will give the array of point 1's position in the \chi_j
        coordinate system. The i element corresponds to varying values of the
        upper frequency cutoff. fMap is used to map between i and actual
        frequencies
    fUpper1 : float
        The upper frequency cutoff of point 1.
    mus2 : List of numpy arrays
        mus2[i] will give the array of point 2's position in the \chi_j
        coordinate system. The i element corresponds to varying values of the
        upper frequency cutoff. fMap is used to map between i and actual
        frequencies
    fUpper2 : float
        The upper frequency cutoff of point 2.
    fMap : dictionary
        fMap[fUpper] will give the index needed to get the \chi_j coordinates
        in the two sets of mus
    norm_map : dictionary
        norm_map[fUpper] will give the relative frequency domain template
        amplitude (sigma) at the given value of fUpper.
    MMdistA
        The minimal mismatch allowed between the points

    Returns
    --------
    Boolean
        True if the points have a mismatch < MMdistA
        False if the points have a mismatch > MMdistA
    """
    f_upper = min(fUpper1, fUpper2)
    f_other = max(fUpper1, fUpper2)
    idx = fMap[f_upper]
    vecs1 = mus1[idx]
    vecs2 = mus2[idx]
    val = ((vecs1 - vecs2)*(vecs1 - vecs2)).sum()
    if (val > MMdistA):
        return False
    # Reduce match to account for normalization.
    norm_fac = norm_map[f_upper] / norm_map[f_other]
    val = 1 - (1 - val)*norm_fac
    return (val < MMdistA)


def find_max_and_min_frequencies(name, mass_range_params, freqs):
    """
    ADD DOCS
    """

    cutoff_fns = pnutils.named_frequency_cutoffs
    if name not in cutoff_fns.keys():
        err_msg = "%s not recognized as a valid cutoff frequency choice." %name
        err_msg += "Recognized choices: " + " ".join(cutoff_fns.keys())
        raise ValueError(err_msg)

    # Can I do this quickly?
    total_mass_approxs = {
        "SchwarzISCO": pnutils.f_SchwarzISCO,
        "LightRing"  : pnutils.f_LightRing,
        "ERD"        : pnutils.f_ERD
    }
    
    if name in total_mass_approxs.keys():
        # This can be done quickly if the cutoff only depends on total mass
        # Assumes that lower total mass = higher cutoff frequency
        upper_f_cutoff = total_mass_approxs[name](mass_range_params.minTotMass)
        lower_f_cutoff = total_mass_approxs[name](mass_range_params.maxTotMass)
    else:
        # Do this numerically
        # FIXME: Is 1000000 the right choice? I think so, but just highlighting
        tot_mass, eta, _, _, _, spin1z, spin2z = \
                get_random_mass(1000000, mass_range_params)
        mass1, mass2 = pnutils.mtotal_eta_to_mass1_mass2(tot_mass, eta)
        mass_dict = {}
        mass_dict['m1'] = mass1
        mass_dict['m2'] = mass2
        mass_dict['s1z'] = spin1z
        mass_dict['s2z'] = spin2z
        tmp_freqs = cutoff_fns[name](mass_dict)
        upper_f_cutoff = tmp_freqs.max()
        lower_f_cutoff = tmp_freqs.min()

    cutoffs = numpy.array([lower_f_cutoff,upper_f_cutoff])
    if lower_f_cutoff < freqs.min():
        warn_msg = "WARNING: "
        warn_msg += "Lowest frequency cutoff is %s Hz " %(lower_f_cutoff,)
        warn_msg += "which is lower than the lowest frequency calculated "
        warn_msg += "for the metric: %s Hz. " %(freqs.min())
        warn_msg += "Distances for these waveforms will be calculated at "
        warn_msg += "the lowest available metric frequency."
        logging.warn(warn_msg)
    if upper_f_cutoff > freqs.max():
        warn_msg = "WARNING: "
        warn_msg += "Highest frequency cutoff is %s Hz " %(upper_f_cutoff,)
        warn_msg += "which is larger than the highest frequency calculated "
        warn_msg += "for the metric: %s Hz. " %(freqs.max())
        warn_msg += "Distances for these waveforms will be calculated at "
        warn_msg += "the largest available metric frequency."
        logging.warn(warn_msg)
    return find_closest_calculated_frequencies(cutoffs, freqs)


def return_nearest_cutoff(name, mass_dict, freqs):
    """
    Given an array of total mass values and an (ascending) list of
    frequencies, this will calculate the specified cutoff formula for each
    mtotal and return the nearest frequency to each cutoff from the input
    list.
    Currently only supports cutoffs that are functions of the total mass
    and no other parameters (SchwarzISCO, LightRing, ERD)

    Parameters
    ----------
    name : string
        Name of the cutoff formula to be approximated
    mass_dict : Dictionary where the keys are used to call the functions
        returned by tmpltbank.named_frequency_cutoffs. The values can be
        numpy arrays or single values.
    freqs : list of floats
        A list of frequencies (must be sorted ascending)

    Returns
    -------
    numpy.array
        The frequencies closest to the cutoff for each value of totmass.
    """
    # A bypass for the redundant case
    if len(freqs) == 1:
        return numpy.zeros(len(mass_dict['m1']), dtype=float) + freqs[0]
    cutoff_fns = pnutils.named_frequency_cutoffs
    if name not in cutoff_fns.keys():
        err_msg = "%s not recognized as a valid cutoff frequency choice." %name
        err_msg += "Recognized choices: " + " ".join(cutoff_fns.keys())
        raise ValueError(err_msg)
    f_cutoff = cutoff_fns[name](mass_dict)
    return find_closest_calculated_frequencies(f_cutoff, freqs)

def find_closest_calculated_frequencies(input_freqs, metric_freqs):
    """
    Given a value (or array) of input frequencies find the closest values in
    the list of frequencies calculated in the metric.

    Parameters
    -----------
    input_freqs : numpy.array or float
        The frequency(ies) that you want to find the closest value in
        metric_freqs
    metric_freqs : numpy.array
        The list of frequencies calculated by the metric

    Returns
    --------
    output_freqs : numpy.array or float
        The list of closest values to input_freqs for which the metric was
        computed
    """
    try:
        refEv = numpy.zeros(len(input_freqs),dtype=float)
    except TypeError:
        refEv = numpy.zeros(1, dtype=float)
        input_freqs = numpy.array([input_freqs])

    if len(metric_freqs) == 1:
        refEv[:] = metric_freqs[0]
        return refEv

    # FIXME: This seems complicated for what is a simple operation. Is there
    #        a simpler *and* faster way of doing this?
    # NOTE: This function assumes a sorted list of frequencies
    # NOTE: totmass and f_cutoff are both numpy arrays as this function is
    #       designed so that the cutoff can be calculated for many systems
    #       simulataneously
    for i in xrange(len(metric_freqs)):
        if i == 0:
            # If frequency is lower than halfway between the first two entries
            # use the first (lowest) value
            logicArr = input_freqs < ((metric_freqs[0] + metric_freqs[1])/2.)
        elif i == (len(metric_freqs)-1):
            # If frequency is larger than halfway between the last two entries
            # use the last (highest) value
            logicArr = input_freqs > ((metric_freqs[-2] + metric_freqs[-1])/2.)
        else:
            # For frequencies within the range in freqs, check which points
            # should use the frequency corresponding to index i.
            logicArrA = input_freqs > ((metric_freqs[i-1] + metric_freqs[i])/2.)
            logicArrB = input_freqs < ((metric_freqs[i] + metric_freqs[i+1])/2.)
            logicArr = numpy.logical_and(logicArrA,logicArrB)
        if logicArr.any():
            refEv[logicArr] = metric_freqs[i]
    return refEv

def outspiral_loop(N):
    """
    Return a list of points that will loop outwards in a 2D lattice in terms
    of distance from a central point. So if N=2 this will be [0,0], [0,1],
    [0,-1],[1,0],[-1,0],[1,1] .... This is useful when you want to loop over
    a number of bins, but want to start in the center and work outwards.
    """
    # Create a 2D lattice of all points
    X,Y = numpy.meshgrid(numpy.arange(-N,N+1), numpy.arange(-N,N+1))

    # Flatten it
    X = numpy.ndarray.flatten(X)
    Y = numpy.ndarray.flatten(Y)

    # Force to an integer
    X = numpy.array(X, dtype=int)
    Y = numpy.array(Y, dtype=int)
   
    # Calculate distances
    G = numpy.sqrt(X**2+Y**2)

    # Combine back into an array
    out_arr = numpy.array([X,Y,G])
   
    # And order correctly
    sorted_out_arr = out_arr[:,out_arr[2].argsort()]

    return sorted_out_arr[:2,:].T
