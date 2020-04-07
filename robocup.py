import pyglet
from pyglet import gl

import Box2D
from Box2D import b2ContactListener, b2Contact, b2Fixture, b2Body, b2Vec2, b2World, b2WeldJointDef

import gym
from gym import spaces
from gym.envs.box2d.car_dynamics import Car
from gym.utils import colorize, seeding, EzPickle

import numpy as np

WINDOW_W = 600
WINDOW_H = 900

FIELD_WIDTH = 8.0
FIELD_HEIGHT = 5.0

FIELD_SCALE = 1 / 3
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

robot_points = [
    (ROBOT_RADIUS * np.cos(-a), ROBOT_RADIUS * np.sin(-a)) for a in robot_angles
]

capture = False
capture_ball_body = None
capture_robot_body = None
capture_anchor = None
joint = None

class CollisionDetector(b2ContactListener):
    """
    A collision detector to keep track of when the robot intercepts the ball
    """

    def __init__(self, env):
        b2ContactListener.__init__(self)
        self.env = env

    def BeginContact(self, contact: b2Contact):
        if contact.touching:
            a_id = contact.fixtureA.body.userData["id"]
            b_id = contact.fixtureB.body.userData["id"]

            if a_id == 0 and b_id == 1:  # a is ball, b is robot
                ball_fixture: b2Fixture = contact.fixtureA
                robot_fixture: b2Fixture = contact.fixtureB
            elif a_id == 1 and b_id == 0:
                ball_fixture: b2Fixture = contact.fixtureB
                robot_fixture: b2Fixture = contact.fixtureA
            else:
                return

            if robot_fixture.userData is not None:
                global capture, capture_ball_body, capture_robot_body, capture_anchor
                capture = True
                manifold: Box2D.b2Manifold = contact.worldManifold
                capture_anchor = manifold.points[0]
                capture_ball_body = ball_fixture.body
                capture_robot_body = robot_fixture.body
                print("Contact with kicker!")

    def EndContact(self, contact):
        pass


class VelocitySpace(spaces.Space):
    """
    Sample a velocity in n-dimensional space. Sampling occurs from a normal
    distribution with given (independent) standard deviation
    """

    def __init__(self, shape, stdev):
        spaces.Space.__init__(self, shape, np.float32)
        self.stdev = stdev
        self.shape = shape

    def sample(self):
        return self.stdev * np.random.randn(*self.shape)

    def contains(self, x):
        return True


class RoboCup(gym.Env, EzPickle):
    def __init__(self, verbose=1):
        EzPickle.__init__(self)
        self.seed()
        self.contactListener_keepref = CollisionDetector(self)
        self.world = Box2D.b2World((0, 0), contactListener=self.contactListener_keepref)
        self.viewer = None

        self.ball = None
        self.robot = None

        self.reward = 0.0
        self.prev_reward = 0.0
        self.verbose = verbose

        self.action_space = spaces.Box(
            np.array([-1.0, -1.0, -1.0]),
            np.array([1.0, 1.0, 1.0]),
            dtype=np.float32
        )

        # Observation space is:
        # [ robot0_x robot0_y robot0_h robot0_vx robot0_vy robot0_vh ]
        # ,
        # [ ball_x ball_y ball_vx ball_vy ]
        self.robot_space = spaces.Tuple([
            spaces.Box(
                np.array([FIELD_MIN_X, FIELD_MIN_Y, 0]),
                np.array([FIELD_MAX_X, FIELD_MAX_Y, np.pi * 2]),
                dtype=np.float32
            ),
            VelocitySpace((3,), np.array([0.5, 0.5, 3.0]))
        ])
        self.ball_space = spaces.Tuple([
            spaces.Box(
                np.array([FIELD_MIN_X, FIELD_MIN_Y]),
                np.array([FIELD_MAX_X, FIELD_MAX_Y]),
                dtype=np.float32
            ),
            VelocitySpace((2,), np.array([2.0, 2.0]))
        ])

        self.observation_space = spaces.Tuple([
            self.robot_space,
            self.ball_space
        ])

        self.reset()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def _destroy(self):
        for body in [
            'ball',
            'top',
            'bottom',
            'left',
            'right',
            'robot',
        ]:
            if body in self.__dict__ and self.__dict__[body] is not None:
                self.world.DestroyBody(self.__dict__[body])
                self.__dict__[body] = None

    def _create(self):
        # Create the goal, robots, ball and field
        self.state = self.observation_space.sample()

        ball_data = {
            "id": 0
        }
        self.ball = self.world.CreateDynamicBody(
            position=(float(self.state[1][0][0]), float(self.state[1][0][1])),
            userData=ball_data
        )
        self.ball.CreateCircleFixture(
            radius=BALL_RADIUS,
            density=BALL_DENSITY,
            restitution=0.4
        )

        self.ball.linearVelocity[0] = float(self.state[1][1][0])
        self.ball.linearVelocity[1] = float(self.state[1][1][1])

        ball_data = {
            "id": 1
        }
        self.robot = self.world.CreateDynamicBody(
            position=(float(self.state[0][0][0]), float(self.state[0][0][1])),
            angle=float(self.state[0][0][2]),
            userData=ball_data
        )
        self.robot.CreatePolygonFixture(
            vertices=robot_points,
            restitution=0.3,
            density=10.0,
        )
        # Kicker rectangle
        self.robot.CreatePolygonFixture(
            vertices=[
                (ROBOT_RADIUS - 0.02, 0.06),
                (ROBOT_RADIUS - 0.02, -0.06),
                (0, -0.06),
                (0, 0.06)
            ],
            restitution=0.1,
            userData={"kicker": True}
        )

        self.robot.linearVelocity[0] = float(self.state[0][1][0])
        self.robot.linearVelocity[1] = float(self.state[0][1][1])
        self.robot.angularVelocity = float(self.state[0][1][2])
        self.robot.linearDamping = 4
        self.robot.angularDamping = 4
        self.robot.fixedRotation = False


        wall_data = {
            "id": -1
        }
        self.top: Box2D.b2Body = self.world.CreateStaticBody(position=(0, 0), userData=wall_data)
        self.top.CreateEdgeFixture(vertices=[
            (VIEW_MIN_X, VIEW_MIN_Y),
            (VIEW_MAX_X, VIEW_MIN_Y)
        ], restitution=1.0)

        self.bottom = self.world.CreateStaticBody(position=(0, 0), userData=wall_data)
        self.bottom.CreateEdgeFixture(vertices=[
            (VIEW_MIN_X, VIEW_MAX_Y),
            (VIEW_MAX_X, VIEW_MAX_Y)
        ], restitution=1.0)

        self.left = self.world.CreateStaticBody(position=(0, 0), userData=wall_data)
        self.left.CreateEdgeFixture(vertices=[
            (VIEW_MIN_X, VIEW_MIN_Y),
            (VIEW_MIN_X, VIEW_MAX_Y)
        ], restitution=1.0)

        self.right = self.world.CreateStaticBody(position=(0, 0), userData=wall_data)
        self.right.CreateEdgeFixture(vertices=[
            (VIEW_MAX_X, VIEW_MIN_Y),
            (VIEW_MAX_X, VIEW_MAX_Y)
        ], restitution=1.0)

    def _applyBallFriction(self):
        # Apply friction to the ball
        ball_speed = np.sqrt(self.ball.linearVelocity[0] ** 2 + self.ball.linearVelocity[1] ** 2)
        FRICTION_LINEAR_REGION = 0.1
        friction_accel = -0.5 * self.ball.linearVelocity / FRICTION_LINEAR_REGION

        if ball_speed > FRICTION_LINEAR_REGION:
            friction_accel = friction_accel * FRICTION_LINEAR_REGION / ball_speed

        friction = self.ball.mass * friction_accel
        self.ball.ApplyForce(friction, self.ball.worldCenter, False)

    def step(self, action):
        # Gather the entire state.
        robot_state = (
            np.array([self.robot.position[0], self.robot.position[1], self.robot.angle]),
            np.array([
                self.robot.linearVelocity[0],
                self.robot.linearVelocity[1],
                self.robot.angularVelocity
            ]),
        )
        ball_state = (np.array([self.ball.position[0], self.ball.position[1]]),
                      np.array([self.ball.linearVelocity[0], self.ball.linearVelocity[1]]))
        self.state = (robot_state, ball_state)

        self.world.Step(1 / 60, 6 * 60, 6 * 60)

        self._applyBallFriction()

        global capture, capture_ball_body, capture_robot_body, capture_anchor, joint

        if capture:
            print("Creating weld joint!")
            joint_def = b2WeldJointDef(bodyA=capture_robot_body, bodyB=capture_ball_body, anchor=capture_anchor)
            joint = self.world.CreateJoint(joint_def)
            capture = False

        step_reward = 0
        done = False
        return self.state, step_reward, done, {}

    def shoot(self):
        global joint
        if joint is not None:
            shoot_magnitude = 0.1
            shoot_force = [shoot_magnitude * np.cos(self.robot.angle), shoot_magnitude * np.sin(self.robot.angle)]
            self.world.DestroyJoint(joint)
            joint = None
            self.ball.ApplyForce(shoot_force, self.robot.worldCenter, True)

    def reset(self):
        self._destroy()
        self.ball = None
        self.state = None
        self._create()

    def render(self):
        if self.viewer is None:
            from gym.envs.classic_control import rendering
            self.viewer = rendering.Viewer(WINDOW_H, WINDOW_W)
            self.viewer.set_bounds(VIEW_MIN_X, VIEW_MAX_X,
                                   VIEW_MIN_Y, VIEW_MAX_Y)

            field_fill = rendering.make_polygon([
                (VIEW_MIN_X, VIEW_MIN_Y),
                (VIEW_MAX_X, VIEW_MIN_Y),
                (VIEW_MAX_X, VIEW_MAX_Y),
                (VIEW_MIN_X, VIEW_MAX_Y)
            ])
            field_fill.set_color(0, 0.5, 0)
            self.viewer.add_geom(field_fill)

            field_outline = rendering.make_polyline([
                (FIELD_MIN_X, FIELD_MIN_Y),
                (FIELD_MAX_X, FIELD_MIN_Y),
                (FIELD_MAX_X, FIELD_MAX_Y),
                (FIELD_MIN_X, FIELD_MAX_Y),
                (FIELD_MIN_X, FIELD_MIN_Y),
            ])
            field_outline.set_color(1, 1, 1)
            self.viewer.add_geom(field_outline)

            ball = rendering.make_circle(BALL_RADIUS)
            ball.set_color(0.8, 0.8, 0.3)
            self.ball_transform = rendering.Transform()
            ball.add_attr(self.ball_transform)
            self.viewer.add_geom(ball)

            robot = rendering.make_polygon(robot_points)
            robot.set_color(0.3, 0.3, 0.3)
            self.robot_transform = rendering.Transform()
            robot.add_attr(self.robot_transform)
            self.viewer.add_geom(robot)

            print("robot_angles: ", robot_angles)

            kicker_width = 0.06
            kicker_depth = 0.02
            kicker_buffer = 0.001
            mouth_x = ROBOT_RADIUS * np.cos(ROBOT_MOUTH_ANGLE / 2) + kicker_buffer
            thing_points = [(mouth_x, kicker_width),
                            (mouth_x, -kicker_width),
                            (mouth_x - kicker_depth, -kicker_width),
                            (mouth_x - kicker_depth, kicker_width)]
            robot_thing = rendering.make_polygon(thing_points)
            robot_thing.set_color(1.0, 0.3, 0.3)
            robot_thing.add_attr(self.robot_transform)
            self.viewer.add_geom(robot_thing)

        self.ball_transform.set_translation(
            self.ball.position[0],
            self.ball.position[1]
        )

        self.robot_transform.set_translation(
            self.robot.position[0],
            self.robot.position[1]
        )
        self.robot_transform.set_rotation(self.robot.angle)

        return self.viewer.render()


if __name__ == '__main__':
    from pyglet.window import key

    restart = False
    env = RoboCup()

    force = [0, 0, 0]
    shoot = False


    def key_press(k, mod):
        global restart
        global force
        global shoot
        if k == key.SPACE:
            restart = True
        if k == key.UP:
            force[1] = 3
        if k == key.DOWN:
            force[1] = -3
        if k == key.LEFT:
            force[0] = -3
        if k == key.RIGHT:
            force[0] = 3
        if k == key.A:
            force[2] = -0.1
        if k == key.D:
            force[2] = 0.1
        if k == key.W:
            shoot = True


    def key_release(k, mod):
        global force, shoot
        if k == key.UP:
            force[1] = 0
        if k == key.DOWN:
            force[1] = 0
        if k == key.LEFT:
            force[0] = 0
        if k == key.RIGHT:
            force[0] = 0
        if k == key.A:
            force[2] = 0
        if k == key.D:
            force[2] = 0
        if k == key.W:
            shoot = False


    env.render()
    env.viewer.window.on_key_press = key_press
    env.viewer.window.on_key_release = key_release

    is_open = True
    while is_open:
        env.reset()
        restart = False
        while True:
            a = None
            env.robot.ApplyForce(force[:2], env.robot.worldCenter, True)
            env.robot.ApplyTorque(force[2], True)
            if shoot:
                shoot = False
                env.shoot()
            s, r, done, info = env.step(a)
            is_open = env.render()
            if done or restart:
                break