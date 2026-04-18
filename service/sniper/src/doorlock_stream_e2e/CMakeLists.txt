cmake_minimum_required(VERSION 3.8)
project(doorlock_stream_e2e)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -O2)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(OpenCV REQUIRED)
find_package(OpenVINO REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GSTREAMER REQUIRED
  gstreamer-1.0>=1.4
  gstreamer-app-1.0>=1.4
)

include_directories(
  include
  ${GSTREAMER_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
)
link_directories(${GSTREAMER_LIBRARY_DIRS})
add_definitions(${GSTREAMER_CFLAGS_OTHER})

# Core library with common utilities
add_library(doorlock_stream_e2e_lib
  src/sniper_preprocessor.cpp
)
target_include_directories(doorlock_stream_e2e_lib PUBLIC include)
target_link_libraries(doorlock_stream_e2e_lib
  ${GSTREAMER_LIBRARIES}
  ${OpenCV_LIBRARIES}
)

add_executable(gst_e2e_sender
  src/gst_e2e_sender.cpp
  vision/detector/guide_light_detector.cpp
)
target_include_directories(gst_e2e_sender PRIVATE
  include
  ${CMAKE_CURRENT_SOURCE_DIR}
)
target_link_libraries(gst_e2e_sender doorlock_stream_e2e_lib)


find_path(PAHO_MQTTCPP_INCLUDE_DIR mqtt/async_client.h)
find_library(PAHO_MQTTCPP_LIB NAMES paho-mqttpp3)
find_library(PAHO_MQTTC_ASYNC_LIB NAMES paho-mqtt3as)

set(HAS_PAHO_MQTT OFF)
if(PAHO_MQTTCPP_INCLUDE_DIR AND PAHO_MQTTCPP_LIB AND PAHO_MQTTC_ASYNC_LIB)
  set(HAS_PAHO_MQTT ON)
endif()

target_link_libraries(gst_e2e_sender
  ${GSTREAMER_LIBRARIES}
  ${OpenCV_LIBRARIES}
  openvino::runtime
  ament_index_cpp::ament_index_cpp
)


if(HAS_PAHO_MQTT)
  add_executable(mqtt_test_receiver
    src/mqtt_test_receiver.cpp
    src/media/gst_decoder_pipeline.cpp
  )
  add_executable(mock_gateway src/mock_gateway.cpp)
  target_include_directories(mqtt_test_receiver PRIVATE ${PAHO_MQTTCPP_INCLUDE_DIR})
  target_include_directories(mock_gateway PRIVATE ${PAHO_MQTTCPP_INCLUDE_DIR})
  target_link_libraries(mqtt_test_receiver
    doorlock_stream_e2e_lib
    ${GSTREAMER_LIBRARIES}
    ${OpenCV_LIBRARIES}
    ${PAHO_MQTTCPP_LIB}
    ${PAHO_MQTTC_ASYNC_LIB}
  )
  target_link_libraries(mock_gateway
    ${PAHO_MQTTCPP_LIB}
    ${PAHO_MQTTC_ASYNC_LIB}
  )
else()
  message(WARNING "mqtt_test_receiver disabled: install libpaho-mqtt-dev and libpaho-mqttpp-dev")
endif()

install(TARGETS gst_e2e_sender
  RUNTIME DESTINATION bin
)

install(DIRECTORY models/
  DESTINATION share/${PROJECT_NAME}/models
)

if(HAS_PAHO_MQTT)
  install(TARGETS mqtt_test_receiver mock_gateway
    RUNTIME DESTINATION bin
  )
endif()

ament_package()
