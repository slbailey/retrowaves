from app.station import Station


def main() -> None:
    """
    Simulation entry point.
    
    Note: run_simulation() method does not exist. Using standard start/run_forever pattern.
    If simulation-specific behavior is needed, it should be implemented separately.
    """
    s = Station()
    s.start()
    # Run for a limited time (simulation mode)
    # For actual simulation, consider implementing a run_simulation() method
    try:
        import time
        time.sleep(5)  # Run for 5 seconds as a simple simulation
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()


if __name__ == "__main__":
    main()


