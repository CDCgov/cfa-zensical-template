class MyExampleClass:
    def __init__(self, x: str):
        """An example class. It has one property.

        Args:
            x (str): A meaningless string-valued property.
        """
        self.x = x

    def what_is_x(self) -> str:
        """A meaningless accessor function.

        Returns:
            str: The value of this class's single property.
        """
        return self.x
