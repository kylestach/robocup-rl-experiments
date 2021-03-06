from robocup_env.envs.base.robocup import RoboCup, InitialConditionConfig
from typing import Tuple
from robocup_env.envs.base.constants import *
from robocup_env.envs.base.robocup_configs import RobocupBaseConfig, BaseRewardConfig
from robocup_env.envs.base.robocup_types import *


class CollectICConfig(InitialConditionConfig):
    def __init__(self):
        #                    x    y    h      bs   vx   vy   vh   bx   by   bvx  bvy
        fixed_ic = np.array([0.5, 0.0, np.pi, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0])
        super().__init__(fixed_ic, enable_scheduled_ic=True)


class CollectConfig(BaseRewardConfig):
    def __init__(self, dribble_count_done: int = 100, dribbling_reward: float = 1.0, done_reward_additive: float = 0.0,
                 done_reward_coeff: float = 500.0, done_reward_exp_base: float = 0.998,
                 survival_reward: float = 0.5,
                 ball_out_of_bounds_reward: float = -100.0, distance_to_ball_coeff: float = -0.1):
        super().__init__()
        self.dribble_count_done = dribble_count_done
        self.dribbling_reward = dribbling_reward

        self.done_reward_additive = done_reward_additive
        self.done_reward_coeff = done_reward_coeff
        self.done_reward_exp_base = done_reward_exp_base

        self.ball_out_of_bounds_reward = ball_out_of_bounds_reward
        self.survival_reward = survival_reward

        self.distance_to_ball_coeff = distance_to_ball_coeff


class RoboCupCollect(RoboCup):
    def __init__(self, base_config: RobocupBaseConfig = RobocupBaseConfig(),
                 collect_config: CollectConfig = CollectConfig(),
                 verbose: bool = True):
        base_config.max_timesteps = 300
        base_config.initial_condition_config = CollectICConfig()
        super().__init__(base_config, verbose)
        self.collect_config = collect_config

    def task_reset(self, scale_factor: float = 0):
        buffer = 1.0
        speed_lim = 0.3
        # Left
        if self.state[BALL_X] <= FIELD_MIN_X + buffer:
            if self.state[BALL_DX] < 0:
                self.state[BALL_X] = FIELD_MIN_X + buffer
            self.state[BALL_DX] = np.clip(self.state[BALL_DX], -speed_lim, np.inf)
        # Right
        if self.state[BALL_X] >= FIELD_MAX_X - buffer:
            if self.state[BALL_DX] > 0:
                self.state[BALL_X] = FIELD_MAX_X - buffer
            self.state[BALL_DX] = np.clip(self.state[BALL_DX], -np.inf, speed_lim)

        # Down
        if self.state[BALL_Y] <= FIELD_MIN_Y + buffer:
            if self.state[BALL_DY] < 0:
                self.state[BALL_Y] = FIELD_MIN_Y + buffer
            self.state[BALL_DY] = np.clip(self.state[BALL_DY], -speed_lim, np.inf)
        # Up
        if self.state[BALL_Y] >= FIELD_MAX_Y - buffer:
            if self.state[BALL_DY] > 0:
                self.state[BALL_Y] = FIELD_MAX_Y - buffer
            self.state[BALL_DY] = np.clip(self.state[BALL_DY], -np.inf, speed_lim)

        total_speed_lim = 1.0
        self.state[BALL_DX] = np.clip(self.state[BALL_DX], -total_speed_lim, total_speed_lim)
        self.state[BALL_DY] = np.clip(self.state[BALL_DY], -total_speed_lim, total_speed_lim)

    def task_logic(self, action: np.ndarray) -> Tuple[float, bool, bool]:
        """
        Performs the task specific logic for calculating the reward and
        episode termination conditions
        @type action: np.ndarray Action passed in
        @return: Tuple of (step_reward, done, got_reward)
        """
        aux_state = self.robot_aux_states[0]
        robot = self.robot_bodies[0]
        aux_state.kick_cooldown = 0

        config = self.collect_config
        done_dribbled = aux_state.dribbling_count >= config.dribble_count_done

        done = done_dribbled
        got_reward = done_dribbled

        dist = np.sqrt((robot.position[0] - self.ball.position[0]) ** 2 + (
                robot.position[1] - self.ball.position[1]) ** 2)

        step_reward = config.survival_reward  # Survival reward
        if done:
            step_reward += config.done_reward_additive + \
                           config.done_reward_coeff * config.done_reward_exp_base ** self.timestep
        elif aux_state.dribbling and not done_dribbled:
            step_reward += config.dribbling_reward
        else:
            step_reward += config.distance_to_ball_coeff * dist

        step_reward += config.move_reward * (
                    np.sum(np.array(action)[:2] ** 2) + config.turn_penalty * action[2] ** 2 + action[3] ** 2)

        # If the ball is out of bounds, and not in the goal, we're done but with low reward
        if not done and (self.ball.position[0] < FIELD_MIN_X or
                         self.ball.position[0] > FIELD_MAX_X or
                         self.ball.position[1] < FIELD_MIN_Y or
                         self.ball.position[1] > FIELD_MAX_Y):
            done = True
            step_reward = config.ball_out_of_bounds_reward

        # If the time limit has exceeded, we're done
        if self.timestep > self.config.max_timesteps:
            done = True
            step_reward = 0

        return step_reward, done, got_reward
