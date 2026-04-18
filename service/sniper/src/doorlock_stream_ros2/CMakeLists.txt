cmake_minimum_required(VERSION 3.8)
project(doorlock_stream_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -O2)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(OpenCV REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GSTREAMER REQUIRED
  gstreamer-1.0>=1.4
  gstreamer-app-1.0>=1.4
)

include_directories(
  ${GSTREAMER_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
)
link_directories(${GSTREAMER_LIBRARY_DIRS})
add_definitions(${GSTREAMER_CFLAGS_OTHER})

add_executable(gst_sender_node src/gst_sender_node.cpp)
ament_target_dependencies(gst_sender_node rclcpp sensor_msgs cv_bridge OpenCV)
target_link_libraries(gst_sender_node ${GSTREAMER_LIBRARIES} ${OpenCV_LIBRARIES})

add_executable(gst_receiver_node src/gst_receiver_node.cpp)
ament_target_dependencies(gst_receiver_node rclcpp sensor_msgs cv_bridge OpenCV)
target_link_libraries(gst_receiver_node ${GSTREAMER_LIBRARIES} ${OpenCV_LIBRARIES})

add_executable(topic_preview_node src/topic_preview_node.cpp)
ament_target_dependencies(topic_preview_node rclcpp sensor_msgs cv_bridge OpenCV)
target_link_libraries(topic_preview_node ${OpenCV_LIBRARIES})

install(TARGETS gst_sender_node gst_receiver_node topic_preview_node
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

ament_package()
