from aiogram.fsm.state import State, StatesGroup


class TrainingStates(StatesGroup):
    waiting_author_position = State()
