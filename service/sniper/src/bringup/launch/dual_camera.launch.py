import os

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    cam1_params_file = LaunchConfiguration('cam1_params_file')
    cam2_params_file = LaunchConfiguration('cam2_params_file')

    start_sender_cam1 = LaunchConfiguration('start_sender_cam1')
    start_sender_cam2 = LaunchConfiguration('start_sender_cam2')
    start_topic_preview = LaunchConfiguration('start_topic_preview')
    start_udp_preview = LaunchConfiguration('start_udp_preview')
    start_shm_preview = LaunchConfiguration('start_shm_preview')
    shm_preview_name = LaunchConfiguration('shm_preview_name')
    shm_preview_scale = LaunchConfiguration('shm_preview_scale')

    cam1_input_topic = LaunchConfiguration('cam1_input_topic')
    cam2_input_topic = LaunchConfiguration('cam2_input_topic')
    topic_preview_input = LaunchConfiguration('topic_preview_input')
    topic_preview_scale = LaunchConfiguration('topic_preview_scale')

    cam1_sender_port = LaunchConfiguration('cam1_sender_port')
    cam2_sender_port = LaunchConfiguration('cam2_sender_port')
    udp_preview_port = LaunchConfiguration('udp_preview_port')

    e2e_receiver_bin = os.path.join(
        get_package_prefix('doorlock_stream_e2e'),
        'bin',
        'gst_e2e_receiver')
    shm_receiver_bin = os.path.join(
        get_package_prefix('doorlock_stream_e2e'),
        'bin',
        'shm_e2e_receiver')

    default_cam1_params = os.path.join(
        get_package_share_directory('hik_camera_ros2_driver'),
        'config',
        'camera_params_cam1_ros.yaml')
    default_cam2_params = os.path.join(
        get_package_share_directory('hik_camera_ros2_driver'),
        'config',
        'camera_params_cam2_noros.yaml')

    cam1_node = Node(
        package='hik_camera_ros2_driver',
        executable='hik_camera_ros2_driver_node',
        namespace='cam1',
        name='hik_camera_ros2_driver',
        parameters=[cam1_params_file],
        output='screen',
        emulate_tty=True,
    )

    cam2_node = Node(
        package='hik_camera_ros2_driver',
        executable='hik_camera_ros2_driver_node',
        namespace='cam2',
        name='hik_camera_ros2_driver',
        parameters=[cam2_params_file],
        output='screen',
        emulate_tty=True,
    )

    cam1_sender_node = Node(
        package='doorlock_stream_ros2',
        executable='gst_sender_node',
        namespace='cam1',
        name='gst_sender_node',
        condition=IfCondition(start_sender_cam1),
        parameters=[{
            'input_topic': cam1_input_topic,
            'host': '127.0.0.1',
            'port': cam1_sender_port,
            'fps': 50,
            'bitrate': 300,
            'mtu': 300,
            'width': 300,
            'height': 300,
        }],
        output='screen',
        emulate_tty=True,
    )

    cam2_sender_node = Node(
        package='doorlock_stream_ros2',
        executable='gst_sender_node',
        namespace='cam2',
        name='gst_sender_node',
        condition=IfCondition(start_sender_cam2),
        parameters=[{
            'input_topic': cam2_input_topic,
            'host': '127.0.0.1',
            'port': cam2_sender_port,
            'fps': 50,
            'bitrate': 300,
            'mtu': 300,
            'width': 300,
            'height': 300,
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
            'window_name': 'ROS2 Topic Preview (Dual)',
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
        DeclareLaunchArgument('cam1_params_file', default_value=default_cam1_params),
        DeclareLaunchArgument('cam2_params_file', default_value=default_cam2_params),
        DeclareLaunchArgument('start_sender_cam1', default_value='false'),
        DeclareLaunchArgument('start_sender_cam2', default_value='false'),
        DeclareLaunchArgument('start_topic_preview', default_value='true'),
        DeclareLaunchArgument('start_udp_preview', default_value='false'),
        DeclareLaunchArgument('start_shm_preview', default_value='true'),
        DeclareLaunchArgument('shm_preview_name', default_value='/cam2_rgb'),
        DeclareLaunchArgument('shm_preview_scale', default_value='2'),
        DeclareLaunchArgument('cam1_input_topic', default_value='/cam1/image_raw'),
        DeclareLaunchArgument('cam2_input_topic', default_value='/cam2/image_raw'),
        DeclareLaunchArgument('topic_preview_input', default_value='/cam1/image_raw'),
        DeclareLaunchArgument('topic_preview_scale', default_value='1'),
        DeclareLaunchArgument('cam1_sender_port', default_value='5600'),
        DeclareLaunchArgument('cam2_sender_port', default_value='5601'),
        DeclareLaunchArgument('udp_preview_port', default_value='5601'),
        cam1_node,
        cam2_node,
        cam1_sender_node,
        cam2_sender_node,
        topic_preview_node,
        udp_preview_process,
        shm_preview_process,
    ])
