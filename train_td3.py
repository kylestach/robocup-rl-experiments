import datetime
from typing import Tuple
import numpy as np
import torch
import gym
import argparse
import os
from torch.utils.tensorboard import SummaryWriter
from utils.schedules import Schedule, LinearSchedule, ConstantSchedule

from utils import ReplayBuffer
from utils import OrnsteinUhlenbeckActionNoise
import TD3


# Runs policy for X episodes and returns average reward
# A fixed seed is used for the eval environment
def eval_policy(policy, env_name, seed, scale: float, eval_episodes=30) -> float:
    """ Eval policy, returning average reward
    @param policy:
    @param env_name:
    @param seed:
    @param scale: Scale used for curriculum. "Difficulty". 0 <= scale <= 1
    @param eval_episodes:
    @return:
    """
    eval_env = gym.make(env_name)
    eval_env.seed(seed + 100)

    rewards = []
    for _ in range(eval_episodes):
        total_reward = 0.0
        state, done = eval_env.reset(scale=scale), False
        while not done:
            action = policy.select_action(np.array(state))
            state, reward, done, _ = eval_env.step(action)
            total_reward += reward

        rewards.append(total_reward)

    avg_reward = sum(rewards) / len(rewards)
    max_reward = max(rewards)
    min_reward = min(rewards)

    print("-----------------------------------------------------------------")
    print(f"Evaluation over {eval_episodes} episodes: "
          f"avg: {avg_reward:.3f}, max: {max_reward:.3f}, min: {min_reward:.3f}")
    print("-----------------------------------------------------------------")
    return avg_reward


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="TD3")  # Policy name (TD3, DDPG or OurDDPG)
    parser.add_argument("--env", default="robocup_env:robocup-collect-v0")  # OpenAI gym environment name
    parser.add_argument("--seed", default=1, type=int)  # Sets Gym, PyTorch and Numpy seeds
    parser.add_argument("--start_timesteps", default=25e3, type=int)  # Time steps initial random policy is used
    parser.add_argument("--eval_freq", default=5e4, type=int)  # How often (time steps) we evaluate
    parser.add_argument("--max_timesteps", default=1e8, type=int)  # Max time steps to run environment
    parser.add_argument("--expl_noise", default=0.1)  # Std of Gaussian exploration noise
    parser.add_argument("--batch_size", default=256, type=int)  # Batch size for both actor and critic
    parser.add_argument("--discount", default=0.99)  # Discount factor
    parser.add_argument("--tau", default=0.005)  # Target network update rate
    parser.add_argument("--policy_noise", default=0.2)  # Noise added to target policy during critic update
    parser.add_argument("--noise_clip", default=0.5)  # Range to clip target policy noise
    parser.add_argument("--policy_freq", default=2, type=int)  # Frequency of delayed policy updates
    parser.add_argument("--save_model", default=True, action="store_true")  # Save model and optimizer parameters
    parser.add_argument("--load_model", default="")  # Model load file name, "" doesn't load, "default" uses file_name
    parser.add_argument("--train_every", default=5, type=int)  # How many timesteps to take between training instances
    parser.add_argument("--print_every", default=10, type=int)  # Print stats for training every X episodes
    parser.add_argument("--save_rewards_every", default=100, type=int)  # Save sampling stats every X timesteps
    parser.add_argument("--log_name", default="default",
                        type=str)  # How many timesteps to take between training instances
    parser.add_argument("--critic_lr", default=3e-4, type=float)  # LR of critic
    parser.add_argument("--actor_lr", default=3e-4, type=float)  # LR of actor
    parser.add_argument("--curriculum", action='store_true')  # Use curriculum
    parser.add_argument("--final_scaling", default=1.0, type=float)  # Use curriculum
    parser.add_argument("--cpu", default=False, action="store_true")  # Force CPU
    args = parser.parse_args()

    for k, v in vars(args).items():
        print(f"{k}: {v}")

    datetime_string = datetime.datetime.today().strftime("%Y-%m-%d_%H:%M:%S")
    file_name = f"{args.policy}_{args.env}_{datetime_string}_{args.log_name}_{args.seed}"
    print("---------------------------------------")
    print(f"Policy: {args.policy}, Env: {args.env}, Seed: {args.seed}")
    print("---------------------------------------")

    if not os.path.exists("./results"):
        os.makedirs("./results")

    if args.save_model and not os.path.exists("./models"):
        os.makedirs("./models")

    env = gym.make(args.env)

    # Set seeds
    env.seed(args.seed)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    # state_dim = 10
    state_dim = env.observation_space.shape[0]
    action_dim = env.action_space.shape[0]
    max_action = float(env.action_space.high[0])

    kwargs = {
        "state_dim": state_dim,
        "action_dim": action_dim,
        "max_action": max_action,
        "discount": args.discount,
        "tau": args.tau,
        "actor_lr": args.actor_lr,
        "critic_lr": args.critic_lr,
    }

    log_dir = "runs"
    writer = SummaryWriter(f"{log_dir}/{args.env}/{datetime_string}/{args.log_name}_{args.seed}")

    # Initialize policy
    if args.policy == "TD3":
        # Target policy smoothing is scaled wrt the action scale
        kwargs["policy_noise"] = args.policy_noise * max_action
        kwargs["noise_clip"] = args.noise_clip * max_action
        kwargs["policy_freq"] = args.policy_freq
        policy = TD3.TD3(**kwargs, force_cpu=args.cpu)
    elif args.policy == "OurDDPG":
        # policy = OurDDPG.DDPG(**kwargs)
        raise NotImplemented
    elif args.policy == "DDPG":
        # policy = DDPG.DDPG(**kwargs)
        raise NotImplemented

    if args.load_model != "":
        policy_file = file_name if args.load_model == "default" else args.load_model
        policy.load(f"./models/{policy_file}")

    replay_buffer = ReplayBuffer(state_dim, action_dim, force_cpu=args.cpu)

    # Evaluate untrained policy
    final_scaling = args.final_scaling
    curriculum_evaluations = [eval_policy(policy, args.env, args.seed, 0)]
    final_evaluations = [eval_policy(policy, args.env, args.seed, final_scaling)]

    state, done = env.reset(scale=0.0), False
    episode_reward = 0
    episode_timesteps = 0
    episode_num = 0

    ou = OrnsteinUhlenbeckActionNoise(np.zeros(action_dim), args.expl_noise * np.ones(action_dim))

    # Curriculum
    scheduling_sigmoid_mult = 1 / 5000000
    scheduling_sigmoid_shift = 3

    schedule: Schedule
    if args.curriculum:
        schedule = LinearSchedule(args.max_timesteps, final_scaling, 0)
    else:
        schedule = ConstantSchedule(final_scaling)

    min_action = env.action_space.low
    max_action = env.action_space.high

    for t in range(int(args.max_timesteps)):

        episode_timesteps += 1

        # Select action randomly or according to policy
        if t < args.start_timesteps:
            action = env.action_space.sample()
            # action = (
            #     ou.noise()
            # ).clip(np.array([-1.0, -1.0, -1.0, 0.0]), np.array([1.0, 1.0, 1.0, 1.0]))
        else:
            action = (
                    policy.select_action(np.array(state))
                    + np.random.normal(0, max_action * args.expl_noise, size=action_dim)
            ).clip(min_action, max_action)

        # Perform action
        next_state, reward, done, _ = env.step(action)
        done_bool = float(done) if episode_timesteps < env._max_episode_steps else 0

        # Store data in replay buffer
        replay_buffer.add(state, action, next_state, reward, done_bool)

        state = next_state
        episode_reward += reward

        # Train agent after collecting sufficient data
        if t >= args.start_timesteps and (t + 1) % args.train_every == 0:
            critic_loss, rewards, q_diff = policy.train(replay_buffer, args.batch_size)
            writer.add_scalar('training/critic_loss', critic_loss, (t + 1))
            writer.add_scalar('training/avg_sampled_reward', rewards.mean().item(), (t + 1))

            if (t + 1) % args.save_rewards_every == 0:
                writer.add_histogram('training/sampled_rewards', reward, (t + 1))
                writer.add_histogram('training/Q_diff', q_diff, (t + 1))

        if done:
            # +1 to account for 0 indexing. +0 on ep_timesteps since it will increment +1 even if done=True
            if episode_num % args.print_every == 0:
                print(f"Total T: {t + 1} Episode Num: {episode_num + 1} Episode T: {episode_timesteps} "
                      f"Reward: {episode_reward:.3f}")

            writer.add_scalar('episode/reward', episode_reward, episode_num)
            writer.add_scalar('episode/timesteps', episode_timesteps, episode_num)

            # Reset environment
            ou.reset()

            # Update scale factor for curriculum learning
            scale = schedule.value(t)
            writer.add_scalar('episode/scale_factor', scale, t)

            state, done = env.reset(scale=scale), False
            episode_reward = 0
            episode_timesteps = 0
            episode_num += 1

        # Evaluate episode
        if (t + 1) % args.eval_freq == 0:
            scale = schedule.value(t)
            curriculum_evaluations.append(eval_policy(policy, args.env, args.seed, scale=scale))
            np.save(f"./results/{file_name}_curriculum", curriculum_evaluations)
            writer.add_scalar('eval/curriculum/average_reward', curriculum_evaluations[-1], (t + 1))

            final_evaluations.append(eval_policy(policy, args.env, args.seed, scale=final_scaling))
            np.save(f"./results/{file_name}_final", final_evaluations)
            writer.add_scalar('eval/final/average_reward', final_evaluations[-1], (t + 1))

            if args.save_model:
                policy.save(f"./models/{file_name}_{t + 1}")
