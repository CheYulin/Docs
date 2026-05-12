/**
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Description: LogConfig Builder for configuring DataSystem logging parameters via environment variables.
 *
 * This is a client-side utility. Include this header in your application code and call
 * Apply() before initializing the DataSystem client (ObjectClient / KvClient / StreamClient).
 *
 * Usage:
 *
 *   // Before creating any DataSystem client
 *   LogEnvConfig::Builder()
 *       .SetMinLogLevel(3)       // 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
 *       .SetLogMonitor(false)    // Disable access recorder
 *       .Apply();
 *
 *   // Then initialize your client
 *   datasystem::ConnectOptions connectOptions;
 *   connectOptions.etcdAddresses = { "127.0.0.1:2379" };
 *   auto client = std::make_shared<datasystem::KVClient>(connectOptions);
 *   (void)client->Init();
 *
 * Note: These environment variables are read once during Logging::Start().
 *       Call Apply() BEFORE any DataSystem client initialization.
 */
#ifndef DATASYSTEM_LOG_ENV_CONFIG_H
#define DATASYSTEM_LOG_ENV_CONFIG_H

#include <cstdlib>
#include <cstring>
#include <string>

namespace datasystem {

/**
 * @brief LogEnvConfig uses environment variables to configure DataSystem logging parameters.
 *
 * This class provides a Builder pattern to set environment variables that DataSystem
 * reads during Logging::Start(). Call Apply() before initializing any DataSystem client.
 *
 * Environment variables set by this config:
 *   - DATASYSTEM_MIN_LOG_LEVEL   -> FLAGS_minloglevel
 *   - DATASYSTEM_LOG_MONITOR_ENABLE -> FLAGS_log_monitor
 */
class LogEnvConfig {
public:
    /**
     * @brief Builder for constructing LogEnvConfig.
     */
    class Builder {
    public:
        /**
         * @brief Set the minimum log level.
         * @param[in] level Log level threshold.
         *   0 = INFO  (all levels logged)
         *   1 = WARNING
         *   2 = ERROR
         *   3 = FATAL (only FATAL logged)
         * @return Reference to Builder for chaining.
         */
        Builder &SetMinLogLevel(int level)
        {
            minLogLevel_ = level;
            minLogLevelSet_ = true;
            return *this;
        }

        /**
         * @brief Enable or disable log monitoring (AccessRecorder).
         * @param[in] enable true to enable, false to disable.
         * @return Reference to Builder for chaining.
         */
        Builder &SetLogMonitor(bool enable)
        {
            logMonitor_ = enable;
            logMonitorSet_ = true;
            return *this;
        }

        /**
         * @brief Apply the configuration by setting environment variables.
         *        Must be called BEFORE initializing any DataSystem client.
         * @return true if all specified parameters were applied successfully.
         */
        bool Apply() const
        {
            bool success = true;

            if (minLogLevelSet_) {
                if (SetEnv("DATASYSTEM_MIN_LOG_LEVEL", std::to_string(minLogLevel_).c_str())) {
                    // OK
                } else {
                    success = false;
                }
            }

            if (logMonitorSet_) {
                const char *value = logMonitor_ ? "true" : "false";
                if (SetEnv("DATASYSTEM_LOG_MONITOR_ENABLE", value)) {
                    // OK
                } else {
                    success = false;
                }
            }

            return success;
        }

    private:
        bool SetEnv(const char *name, const char *value) const
        {
            // Using setenv is safe in single-threaded context before client init.
            // In multi-threaded context, ensure Apply() is called before spawning threads.
            if (::setenv(name, value, 1) != 0) {
                return false;
            }
            return true;
        }

        int minLogLevel_ = 0;
        bool minLogLevelSet_ = false;
        bool logMonitor_ = true;
        bool logMonitorSet_ = false;
    };

    /**
     * @brief Convenience function to disable all logging with one call.
     *        Sets minLogLevel=3 (FATAL only) and logMonitor=false.
     * @return true if environment variables were set successfully.
     */
    static bool DisableAllLogging()
    {
        return Builder()
            .SetMinLogLevel(3)
            .SetLogMonitor(false)
            .Apply();
    }
};

}  // namespace datasystem

#endif  // DATASYSTEM_LOG_ENV_CONFIG_H
