# overhead

import logging
import math
import random
import time

import matplotlib.pyplot as plt
import numpy as np
import torch as t
import torch.nn as nn
from torch import optim
from torch.nn import utils

logger = logging.getLogger(__name__)

# environment parameters

FRAME_TIME = 1.0  # time interval, originally =0.1
GRAVITY_ACCEL = -9.81/1000  # gravity constant       Make sure it's negative
BOOST_ACCEL = 14.715/1000  # thrust constant

# # the following parameters are not being used in the sample code
# PLATFORM_WIDTH = 0.25  # landing platform width
# PLATFORM_HEIGHT = 0.06  # landing platform height
# ROTATION_ACCEL = 20  # rotation constant

# define system dynamics
# Notes: 
# 0. You only need to modify the "forward" function !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!   
# 1. All variables in "forward" need to be PyTorch tensors.
# 2. All math operations in "forward" has to be differentiable, e.g., default PyTorch functions.
# 3. Do not use inplace operations, e.g., x += 1. Please see the following section for an example that does not work.

class Dynamics(nn.Module):

    def __init__(self):
        super(Dynamics, self).__init__()

    @staticmethod
    def forward(state, action):

        """
        action: thrust or no thrust
        state[0] = y
        state[1] = y_dot
        """
        
        # Apply gravity
        # Note: Here gravity is used to change velocity which is the second element of the state vector
        # Normally, we would do x[1] = x[1] + gravity * delta_time
        # but this is not allowed in PyTorch since it overwrites one variable (x[1]) that is part of the computational graph to be differentiated.
        # Therefore, I define a tensor dx = [0., gravity * delta_time], and do x = x + dx. This is allowed... 
        delta_state_gravity = t.tensor([0., 0., 0., GRAVITY_ACCEL * FRAME_TIME, 0.])

        # Thrust
        # Going off of what we talked about in lecture for including problem statement 
        N= len(state)
        
        state_tensor= t.zeros((N, 5)) #setting matrix full of zeros
        state_tensor[:, 1]= -t.sin(state[:, 4]) # Vx       
        state_tensor[:, 3]= t.cos(state[:, 4])  # Vy 
        
        delta_state = BOOST_ACCEL * FRAME_TIME * t.mul(state_tensor, action[:, 0].reshape(-1, 1))
        
        #Theta
        delta_state_theta= FRAME_TIME * t.mul(t.tensor([0., 0., 0., 0., -1.]), action[:, 1].reshape(-1, 1))

        # Update velocity   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!     think I got it
        state_copy = state # Don't think you can have inline operation 'state=state+...'
        
        # drag force, applying it directly to velocity, "state"
        coeff= 0.75 # typical value for the drag coeff of a model rocket, from grc.nasa.gov
        p= 1.29 # density of air
        A= 10.75 # average diameter of rocket = 3.7 [m], from space.stackexchange.com
        drag= (-0.5)*coeff*p*A # *velocity^2
        # c: coeff of drag  A: surface/cross sectional area v: velocity p= air density
        
        state = state_copy + delta_state + delta_state_gravity + delta_state_theta + drag*state_copy**2 
        
        # Update state !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Think I got it
        # Note: Same as above. Use operators on matrices/tensors as much as possible. Do not use element-wise operators as they are considered inplace.
        step_mat = t.tensor([[1., FRAME_TIME, 0., 0., 0.],
                            [0., 1., 0., 0., 0.],
                            [0., 0., 1., FRAME_TIME, 0.],
                            [0., 0., 0., 1., 0.],
                            [0., 0., 0., 0., 1.]])
        state = t.matmul(step_mat, state)      
        return state 
    
# a deterministic controller
# Note:
# 0. You only need to change the network architecture in "__init__"   !!!!!!!!!!!!!!!!!!!!!!!!
# 1. nn.Sigmoid outputs values from 0 to 1, nn.Tanh from -1 to 1
# 2. You have all the freedom to make the network wider (by increasing "dim_hidden") or deeper (by adding more lines to nn.Sequential)
# 3. Always start with something simple

class Controller(nn.Module):

    def __init__(self, dim_input, dim_hidden, dim_output):
        """
        dim_input: # of system states
        dim_output: # of actions
        dim_hidden: up to you
        """
        super(Controller, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(dim_input, dim_hidden),
            nn.Tanh(),
            nn.Linear(dim_hidden, dim_output),
            # You can add more layers here
            nn.Sigmoid()
        )

    def forward(self, state):
        action = self.network(state)              
        return action
    
    
    
# the simulator that rolls out x(1), x(2), ..., x(T)
# Note:
# 0. Need to change "initialize_state" to optimize the controller over a distribution of initial states   !!!!!
# 1. self.action_trajectory and self.state_trajectory stores the action and state trajectories along time

class Simulation(nn.Module):

    def __init__(self, controller, dynamics, T):
        super(Simulation, self).__init__()
        self.state = self.initialize_state()
        self.controller = controller
        self.dynamics = dynamics
        self.T = T
        self.action_trajectory = []
        self.state_trajectory = []

    def forward(self, state):
        self.action_trajectory = []
        self.state_trajectory = []
        for _ in range(T):
            action = self.controller.forward(state)
            state = self.dynamics.forward(state, action)
            self.action_trajectory.append(action)
            self.state_trajectory.append(state)
        return self.error(state)

    @staticmethod
    def initialize_state():
        state = [0., 0., 1., 0., 0.]  # TODO: need batch of initial states   !!!!!!!!!!!!!!!!!!!! 
        return t.tensor(state, requires_grad=False).float()

    def error(self, state):
        return state[0]**2 + state[1]**2    
    
# set up the optimizer
# Note:
# 0. LBFGS is a good choice if you don't have a large batch size (i.e., a lot of initial states to consider simultaneously)
# 1. You can also try SGD and other momentum-based methods implemented in PyTorch
# 2. You will need to customize "visualize"     !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# 3. loss.backward is where the gradient is calculated (d_loss/d_variables)
# 4. self.optimizer.step(closure) is where gradient descent is done

        # t.autograd.set_detect_anomaly(True)  #used to help identify error TW 
        # error is related to an inplace operation effecting 'loss.backward()', 
        #       don't think I need this anymore

class Optimize:
    def __init__(self, simulation):
        self.simulation = simulation
        self.parameters = simulation.controller.parameters()
        self.optimizer = optim.LBFGS(self.parameters, lr=0.5)  
        # originally: lr=0.01 took 28 iter, 21 iter at 0.1, 25 iter at 0.001, 20 iter at 0.5

    def step(self):
        def closure():
            loss = self.simulation(self.simulation.state)
            self.optimizer.zero_grad()
            loss.backward()                                     
            return loss
        self.optimizer.step(closure)
        return closure()
    
    def train(self, epochs):
        for epoch in range(epochs):
            loss = self.step()
            self.visualize()

    def visualize(self):
        data = np.array([self.simulation.state_trajectory[i].detach().numpy() for i in range(self.simulation.T)])
        x = data[:, 0]
        y = data[:, 1]
        plt.plot(x, y)   
        plt.show()
        
        
# Now it's time to run the code!

T = 20  # number of time steps      originally, T=100
dim_input = 5  # state space dimensions     = #of initial states (line 144)   
dim_hidden = 6  # latent dimensions
dim_output = 1  # action space dimensions
d = Dynamics()  # define dynamics
c = Controller(dim_input, dim_hidden, dim_output)  # define controller
s = Simulation(c, d, T)  # define simulation
o = Optimize(s)  # define optimizer
o.train(40)  # solve the optimization problem   originally =40 
                  
