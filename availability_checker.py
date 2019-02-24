import datetime
import textwrap
from collections import OrderedDict
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from email_notifier import EmailNotifier
from game_status import GameStatus
from notifier_factory import NotifierFactory
from sql_dao import SQLDao
from utility import debug


class AvailabilityChecker(object):
    SOLD_OUT = 'SOLD OUT'

    def build_urls(self):
        base_url = 'https://secure.stinkysocks.net/NCH/NCH-'
        hours = [21, 22]
        weeks_ahead = 2

        urls = OrderedDict()
        today = datetime.date.today()
        for week_ahead in range(weeks_ahead):
            tuesday = today + datetime.timedelta(((1-today.weekday()) % 7) + week_ahead * 7)
            for hour in hours:
                tuesday_dt = datetime.datetime.combine(tuesday, datetime.datetime.min.time())
                tuesday_dt = tuesday_dt.replace(hour=hour, minute=0)
                urls[tuesday_dt] = base_url + tuesday_dt.strftime('%Y%m%d%H%S') + 'SOM.html'

        return urls

    def get_game_statuses(self, sql_dao):
        urls = self.build_urls()

        game_statuses = []
        for day, url in urls.items():
            print('Checking {}: {}...'.format(day, url))
            try:
                request = Request(url, headers={'User-Agent' : "Magic Browser"})
                connection = urlopen(request)

                soup = BeautifulSoup(connection, 'html.parser')
                game_status_button = soup.find('a', attrs={'class': 'more-info'})

                is_game_sold_out = bool(game_status_button and self.SOLD_OUT in game_status_button.text)
                game_status = GameStatus(day, url, is_game_sold_out, sql_dao)
                game_statuses.append(game_status)
                game_status.set_prior_game_availability()

                # If this game never existed lets insert it.
                if game_status.was_game_sold_out is None:
                    game_status.insert_game()

            except Exception as e:
                debug("Exception getting game status: {}".format(e))
                game_status = GameStatus(day, url, None, sql_dao)
                game_statuses.append(game_status)

        print("All Hockey Games: ")
        print(sql_dao.get_hockey_games())

        return game_statuses

    def check_game_availability(self):
        notifier = None
        sql_dao = SQLDao()
        try :
            sql_dao.build_hockey_games_table()
            notifier = NotifierFactory.get_notifier()
            game_statuses = self.get_game_statuses(sql_dao)

            did_game_change = any([g.did_game_become_available() for g in game_statuses])
            if did_game_change:
                print("A game changed to available, sending notification...")
                notifier.send_game_status_emails(game_statuses)
            else:
                print("No game changed state, not sending notification...")
                if len([g for g in game_statuses if g.is_game_sold_out is None]) == len(game_statuses):
                    print("Errors getting game availability, sending notification...")
                    notifier.send_error_email()
        except Exception as e:
            print('Exception during execution: {}'.format(e))

        finally:
            if isinstance(notifier, EmailNotifier):
                print('Closing SMTP Connection')
                notifier.close()
