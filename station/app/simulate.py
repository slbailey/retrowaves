from app.station import Station


def main() -> None:
    s = Station()
    s.run_simulation(segments=5)


if __name__ == "__main__":
    main()


