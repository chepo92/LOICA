import numpy as np
from numpy.fft import fft, ifft, fftfreq
from scipy.optimize import least_squares
from scipy.interpolate import interp1d

from .source import *
from flapjack import *

class Receiver:
    def __init__(self, inducer, output, a, b, K, n, profile=None):
        if profile:
            self.profile = profile
        else:
            def profile(t):
                return 1
            self.profile = profile
        self.a = a
        self.b = b
        self.K = K
        self.n = n
        self.receptor = 0
        self.inducer = inducer
        self.output = output
        
    def expression_rate(self, t, dt):
        inducer = self.inducer.concentration
        i = (inducer/self.K)**self.n
        expression_rate = self.profile(t) * ( self.a + self.b*i ) / (1 + i)
        return expression_rate

    def forward_model(
            self,
            K_A=1,
            n_A=2,
            Dt=0.05,
            sim_steps=10,
            A=[0],
            odval=[1]*100,
            profile=[1]*100,
            gamma=0,
            p0=0,
            nt=100
        ):
        p1_list,A_list,t_list = [],[],[]
        p1 = np.zeros_like(A) + p0
        for t in range(nt):
            p1_list.append(p1)
            A_list.append(A)
            t_list.append([t * Dt]*len(A))
            od = odval[t]
            tt = t*Dt
            prof = profile[t]
            for tt in range(sim_steps):
                a = (A/K_A)**n_A
                nextp1 = p1 + (od * prof * a/(1 + a) - gamma*p1) * Dt/sim_steps
                p1 = nextp1


        ap1 = np.array(p1_list).transpose()
        AA = np.array(A_list).transpose()
        tt = np.array(t_list).transpose()
        t = np.arange(nt) * Dt
        return ap1,AA,tt

    def residuals(self, data, p0, A, odval, epsilon, dt, t, n_gaussians): 
        def func(x): 
            K_A = x[0]
            n_A = x[1]        
            nt = len(t)
            means = np.linspace(t.min(), t.max(), n_gaussians)
            vars = [(t.max()-t.min())/n_gaussians]*n_gaussians 
            heights = x[2:]
            profile = np.zeros_like(t)
            for mean,var,height in zip(means, vars, heights):
                gaussian = height * np.exp(-(t-mean)*(t-mean) / var / 2) / np.sqrt(2 * np.pi * var)
                profile += gaussian
            p,AA,tt = self.forward_model(
                        K_A=K_A,
                        n_A=n_A,
                        Dt=dt,
                        A=A,
                        odval=odval,
                        profile=profile,
                        nt=nt,
                        p0=p0
                    )
            model = p.ravel()
            residual = data - model
            tikhonov = heights
            total_variation = np.sqrt(np.abs(np.diff(profile)))
            result = np.concatenate((residual, epsilon * tikhonov))
            return result
        return func


    def characterize(self, flapjack, vector, media, strain, signal, biomass_signal, n_gaussians, epsilon):
        expression = flapjack.analysis(media=media, 
                            strain=strain,
                            vector=vector,
                            signal=signal,
                            type='Background Correct',
                            biomass_signal=biomass_signal
                            )
        # Inducer concentrations
        A = expression.groupby('Concentration1').mean().index.values
        # Group and average data
        expression = expression.sort_values(['Sample', 'Concentration1', 'Time'])
        # Time points and interval
        t = expression.Time.unique()
        dt = np.diff(t).mean()
        # Take mean of samples
        expression = expression.groupby(['Concentration1', 'Time']).mean().Measurement.values

        biomass = flapjack.analysis(media=media, 
                            strain=strain,
                            vector=vector,
                            signal=biomass_signal,
                            type='Background Correct',
                            biomass_signal=biomass_signal
                            )
        biomass = biomass.sort_values(['Sample', 'Concentration1', 'Time'])        
        biomass = biomass.groupby('Time').mean().Measurement.values

        nt = len(t)
        # Bounds for fitting
        lower_bounds = [0]*2 + [0]*n_gaussians
        upper_bounds = [1e2, 4] + [1e8]*n_gaussians
        bounds = [lower_bounds, upper_bounds]
        '''
            K_A = x[0]
            n_A = x[1]
            profile = x[2:]
        '''

        data = expression.ravel()
        res = least_squares(
                self.residuals(
                    data, data[0], A, biomass, epsilon=epsilon, dt=dt, t=t, n_gaussians=n_gaussians
                    ), 
                [0, 0] + [1]*n_gaussians, 
                bounds=bounds
                )
        self.res = res
        self.K = res.x[0]
        self.n = res.x[1]
        profile = np.zeros_like(t)
        means = np.linspace(t.min(), t.max(), n_gaussians)
        vars = [(t.max()-t.min())/n_gaussians] * n_gaussians 
        heights = res.x[2:]
        for mean,var,height in zip(means, vars, heights):
            gaussian = height * np.exp(-(t-mean)*(t-mean) / var / 2) / np.sqrt(2 * np.pi * var)
            profile += gaussian
        self.b = profile.max()
        self.profile = interp1d(t, profile/self.b, fill_value='extrapolate', bounds_error=False)
        self.a = 0
