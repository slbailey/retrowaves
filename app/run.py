from app.station import Station


def main() -> None:
    s = Station()
    try:
        s.start()
    except KeyboardInterrupt:
        s.stop()


if __name__ == "__main__":
    main()


