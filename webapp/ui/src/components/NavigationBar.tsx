import React from "react";
import { Flex, Heading } from "@chakra-ui/react";

const NavigationBar = ({ title = "dicompare" }) => {
  return (
    <Flex
      justify="space-between"
      align="center"
      padding="1rem 2rem"
      bg="teal.500"
      color="white"
      boxShadow="md"
    >
      <Heading as="h1" size="xl">
        {title}
      </Heading>
    </Flex>
  );
};

export default NavigationBar;
