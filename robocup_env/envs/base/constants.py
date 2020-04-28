import numpy as np

WINDOW_W = 600
WINDOW_H = 900

FIELD_WIDTH = 8.0
FIELD_HEIGHT = 5.0

FIELD_SCALE = 1 / 2
FIELD_MIN_X = -4.0 * FIELD_SCALE
FIELD_MAX_X = 4.0 * FIELD_SCALE
FIELD_MIN_Y = -2.5 * FIELD_SCALE
FIELD_MAX_Y = 2.5 * FIELD_SCALE

VIEW_MIN_X = -4.5 * FIELD_SCALE
VIEW_MAX_X = 4.5 * FIELD_SCALE
VIEW_MIN_Y = -3.0 * FIELD_SCALE
VIEW_MAX_Y = 3.0 * FIELD_SCALE

BALL_RADIUS = 0.02
BALL_DENSITY = 0.7

NUM_ROBOTS = 1

ROBOT_RADIUS = 0.09
ROBOT_MOUTH_ANGLE = np.deg2rad(80)
robot_angles = list(np.linspace(
    ROBOT_MOUTH_ANGLE / 2,
    2 * np.pi - ROBOT_MOUTH_ANGLE / 2,
    15))

GOAL_HEIGHT = FIELD_HEIGHT / 6
GOAL_DEPTH = 0.3

LEFT_GOAL_X = FIELD_MIN_X
LEFT_GOAL_Y = 0
LEFT_GOAL_POINTS = [
    (FIELD_MIN_X - GOAL_DEPTH, GOAL_HEIGHT / 2),
    (FIELD_MIN_X, GOAL_HEIGHT / 2),
    (FIELD_MIN_X, -GOAL_HEIGHT / 2),
    (FIELD_MIN_X - GOAL_DEPTH, -GOAL_HEIGHT / 2)
]
BALL_FORCE_MULT = 5.0

robot_points = [
    (ROBOT_RADIUS * np.cos(-a), ROBOT_RADIUS * np.sin(-a)) for a in robot_angles
]

KICK_THRESHOLD = 0.5
FRICTION_LINEAR_REGION = 0.1