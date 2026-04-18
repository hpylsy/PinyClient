import os

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    camera_params_file = LaunchConfiguration('camera_params_file')
    start_ros2_sender = LaunchConfiguration('start_ros2_sender')
    start_ros2_receiver = LaunchConfiguration('start_ros2_receiver')
    start_topic_preview = LaunchConfiguration('start_topic_preview')
    start_udp_preview = LaunchConfiguration('start_udp_preview')
    start_shm_preview = LaunchConfiguration('start_shm_preview')
    shm_preview_name = LaunchConfiguration('shm_preview_name')
    shm_preview_scale = LaunchConfiguration('shm_preview_scale')
    sender_input_topic = LaunchConfiguration('sender_input_topic')
    topic_preview_input = LaunchConfiguration('topic_preview_input')
    topic_preview_scale = LaunchConfiguration('topic_preview_scale')

    sender_host = LaunchConfiguration('sender_host')
    sender_port = LaunchConfiguration('sender_port')
    sender_fps = LaunchConfiguration('sender_fps')
    sender_bitrate = LaunchConfiguration('sender_bitrate')
    sender_mtu = LaunchConfiguration('sender_mtu')
    sender_width = LaunchConfiguration('sender_width')
    sender_height = LaunchConfiguration('sender_height')

    receiver_port = LaunchConfiguration('receiver_port')
    receiver_jitter = LaunchConfiguration('receiver_jitter')
    receiver_output_topic = LaunchConfiguration('receiver_output_topic')
    udp_preview_port = LaunchConfiguration('udp_preview_port')

    e2e_receiver_bin = os.path.join(
        get_package_prefix('doorlock_stream_e2e'),
        'bin',
        'gst_e2e_receiver')
    shm_receiver_bin = os.path.join(
        get_package_prefix('doorlock_stream_e2e'),
        'bin',
        'shm_e2e_receiver')

    default_camera_params = os.path.join(
        get_package_share_directory('hik_camera_ros2_driver'),
        'config',
        'camera_params.yaml')

    camera_node = Node(
        package='hik_camera_ros2_driver',
        executable='hik_camera_ros2_driver_node',
        name='hik_camera_ros2_driver',
        parameters=[camera_params_file],
        output='screen',
        emulate_tty=True,
    )

    ros2_sender_node = Node(
        package='doorlock_stream_ros2',
        executable='gst_sender_node',
        name='gst_sender_node',
        condition=IfCondition(start_ros2_sender),
        parameters=[{
            'input_topic': sender_input_topic,
            'host': sender_host,
            'port': sender_port,
            'fps': sender_fps,
            'bitrate': sender_bitrate,
            'mtu': sender_mtu,
            'width': sender_width,
            'height': sender_height,
        }],
        output='screen',
        emulate_tty=True,
    )

    ros2_receiver_node = Node(
        package='doorlock_stream_ros2',
        executable='gst_receiver_node',
        name='gst_receiver_node',
        condition=IfCondition(start_ros2_receiver),
        parameters=[{
            'port': receiver_port,
            'jitter_latency': receiver_jitter,
            'output_topic': receiver_output_topic,
        }],
        output='screen',
        emulate_tty=True,
    )

    topic_preview_node = Node(
        package='doorlock_stream_ros2',
        executable='topic_preview_node',
        name='topic_preview_node',
        condition=IfCondition(start_topic_preview),
        parameters=[{
            'input_topic': topic_preview_input,
            'window_name': 'ROS2 Topic /image_raw',
            'display_scale': topic_preview_scale,
        }],
        output='screen',
        emulate_tty=True,
    )

    udp_preview_process = ExecuteProcess(
        condition=IfCondition(start_udp_preview),
        cmd=[
            e2e_receiver_bin,
            '--port', udp_preview_port,
            '--jitter-latency', '5',
            '--display-scale', '2',
            '--show-raw', 'true',
            '--show-overlay', 'true',
        ],
        output='screen',
    )

    shm_preview_process = ExecuteProcess(
        condition=IfCondition(start_shm_preview),
        cmd=[
            shm_receiver_bin,
            '--shm-name', shm_preview_name,
            '--display-scale', shm_preview_scale,
            '--window-name', 'SHM Preview',
        ],
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument('camera_params_file', default_value=default_camera_params),
        DeclareLaunchArgument('start_ros2_sender', default_value='false'),
        DeclareLaunchArgument('start_ros2_receiver', default_value='false'),
        DeclareLaunchArgument('start_topic_preview', default_value='true'),
        DeclareLaunchArgument('start_udp_preview', default_value='false'),
        DeclareLaunchArgument('start_shm_preview', default_value='true'),
        DeclareLaunchArgument('shm_preview_name', default_value='/hik_camera_rgb'),
        DeclareLaunchArgument('shm_preview_scale', default_value='2'),
        DeclareLaunchArgument('sender_input_topic', default_value='/image_raw'),
        DeclareLaunchArgument('topic_preview_input', default_value='/image_raw'),
        DeclareLaunchArgument('topic_preview_scale', default_value='1'),
        DeclareLaunchArgument('sender_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('sender_port', default_value='5600'),
        DeclareLaunchArgument('sender_fps', default_value='50'),
        DeclareLaunchArgument('sender_bitrate', default_value='300'),
        DeclareLaunchArgument('sender_mtu', default_value='300'),
        DeclareLaunchArgument('sender_width', default_value='300'),
        DeclareLaunchArgument('sender_height', default_value='300'),
        DeclareLaunchArgument('receiver_port', default_value='5600'),
        DeclareLaunchArgument('receiver_jitter', default_value='5'),
        DeclareLaunchArgument('receiver_output_topic', default_value='/gst/image_raw'),
        DeclareLaunchArgument('udp_preview_port', default_value='5600'),
        camera_node,
        ros2_sender_node,
        ros2_receiver_node,
        topic_preview_node,
        udp_preview_process,
        shm_preview_process,
    ])
