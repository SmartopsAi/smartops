from apps.policy_engine.dsl.parser import parse_policies

dsl_text = """
POLICY "restart_on_memory_leak":
  WHEN rca.cause == "memory_leak"
  THEN restart(service)
  PRIORITY 1

POLICY "scale_on_cpu_saturation":
  WHEN rca.cause == "cpu_saturation"
  THEN scale(service, 6)
  PRIORITY 10

POLICY "restart_on_high_latency":
  WHEN anomaly.type == "latency" AND anomaly.score > 0.85
  THEN restart(service)
  PRIORITY 5
"""


def main():
    policies = parse_policies(dsl_text)
    print("Parsed policies:")
    for p in policies:
        print(" -", p)


if __name__ == "__main__":
    main()
