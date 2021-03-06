# Copyright (C) 2019 Vasiliy Sheredeko
#
# This software may be modified and distributed under the terms
# of the MIT license.  See the LICENSE file for details.
from __future__ import annotations

from orcinus.core.diagnostics import DiagnosticManager
from orcinus.language.scanner import Scanner
from orcinus.language.syntax import *
from orcinus.utils import camel_case_to_lower_space


class Parser:
    IMPORTS_STARTS = (TokenID.Import, TokenID.From)
    MEMBERS_STARTS = (TokenID.Pass, TokenID.Def, TokenID.Class, TokenID.Struct, TokenID.Name, TokenID.LeftSquare)
    EXPRESSION_STARTS = (
        TokenID.Number, TokenID.Name, TokenID.LeftParenthesis, TokenID.Plus, TokenID.Minus, TokenID.Tilde
    )
    STATEMENT_STARTS = EXPRESSION_STARTS + (TokenID.Pass, TokenID.Return, TokenID.While, TokenID.If)

    def __init__(self, filename, stream, *, diagnostics: DiagnosticManager = None):
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticManager()
        self.tokens = list(Scanner(filename, stream, diagnostics=diagnostics))
        self.index = 0
        self.is_error_mode = False  # marker for error mode

    @property
    def current_token(self) -> SyntaxToken:
        return self.tokens[self.index]

    @property
    def previous_location(self) -> Location:
        location = self.current_token.location
        return Location(location.filename, location.begin, location.begin)

    def match(self, *indices: TokenID) -> bool:
        """
        Match current token

        :param indices:     Token identifiers
        :return: True, if current token is matched passed identifiers
        """
        return self.current_token.id in indices

    def consume(self, *indices: TokenID) -> SyntaxToken:
        """
        Consume current token. If token is not matched required IDs then go to error mode and return error token

        :param indices:     Token identifiers
        :return: Return consumed token
        :raise Diagnostic if current token is not matched passed identifiers
        """

        # check
        if not indices or self.match(*indices):
            token = self.current_token
            if self.index < len(self.tokens) - 1:
                self.index += 1
            return token

        # generate exception message
        if not self.is_error_mode:
            self.is_error_mode = True
            message = self.get_error_message(*indices)
            self.diagnostics.error(self.current_token.location, message)

        # return error token
        return SyntaxToken(TokenID.Error, '', self.previous_location)

    def resume(self, *indices: TokenID):
        """ Resume normal mode by set of synchronizing tokens """
        trivia = []
        while not self.match(*indices):
            trivia.append(self.consume())

        self.is_error_mode = False
        return self.consume(*indices)

    def get_error_message(self, *indices: TokenID):
        existed_name = camel_case_to_lower_space(self.current_token.id.name)
        if len(indices) > 1:
            required_names = ', '.join(f'‘{camel_case_to_lower_space(x.name)}’' for x in indices)
            return f"Expected one of {required_names}, but got ‘{existed_name}’"
        else:
            required_name = camel_case_to_lower_space(indices[0].name)
            return f"Expected ‘{required_name}’, but got ‘{existed_name}’"

    def parse(self) -> SyntaxTree:
        """
        Parse module from source

        module:
            members EndFile
        """
        imports = self.parse_imports()
        members = self.parse_members()
        tok_eof = self.consume(TokenID.EndFile)

        # noinspection PyArgumentList
        return SyntaxTree(imports=imports, members=members, tok_eof=tok_eof)

    def parse_type(self) -> TypeAST:
        """
        type:
            atom_type { generic_arguments }
        """
        result_type = self.parse_atom_type()
        while self.match(TokenID.LeftSquare):
            arguments = self.parse_generic_arguments()

            # noinspection PyArgumentList
            result_type = ParameterizedTypeAST(type=result_type, arguments=arguments, location=result_type.location)
        return result_type

    def parse_atom_type(self) -> TypeAST:
        """
        atom_type:
            Name
        """
        tok_name = self.consume(TokenID.Name)

        # noinspection PyArgumentList
        return NamedTypeAST(tok_name=tok_name)

    def parse_generic_parameters(self) -> Sequence[GenericParameterAST]:
        """
        generic_parameters
            : [ '[' generic_parameter { ',' generic_parameter } ] ']' ]
        """
        if not self.match(TokenID.LeftSquare):
            return SyntaxCollection(location=self.previous_location)

        parameters = [
            self.consume(TokenID.LeftSquare),
            self.parse_generic_parameter()
        ]
        while self.match(TokenID.Comma):
            parameters.append(self.consume(TokenID.Comma))
            parameters.append(self.parse_generic_parameter())
        parameters.append(self.consume(TokenID.RightSquare))

        return SyntaxCollection(parameters)

    def parse_generic_parameter(self) -> GenericParameterAST:
        """
        generic_parameter
            Name
        """
        tok_name = self.consume(TokenID.Name)

        # noinspection PyArgumentList
        return GenericParameterAST(tok_name)

    def parse_generic_arguments(self) -> Sequence[TypeAST]:
        """
        generic_arguments:
            '[' type { ',' type} ']'
        """
        self.consume(TokenID.LeftSquare)
        arguments = [self.parse_type()]
        while self.match(TokenID.Comma):
            self.consume(TokenID.Comma)
            arguments.append(self.parse_type())
        self.consume(TokenID.RightSquare)
        return tuple(arguments)

    def parse_imports(self) -> Sequence[ImportAST]:
        """
        imports:
            { import }
        """
        imports = []
        while self.match(*self.IMPORTS_STARTS):
            imports.append(self.parse_import())
        return SyntaxCollection(imports, location=self.previous_location)

    def parse_import(self) -> ImportAST:
        """
        import:
            'import' aliases
            'from' qualified_name 'import' aliases
        """
        if self.match(TokenID.From):
            tok_from = self.consume(TokenID.From)
            qualified_name = self.parse_qualified_name()
            tok_import = self.consume(TokenID.Import)
            aliases = self.parse_aliases()
            tok_newline = self.resume(TokenID.NewLine)

            # noinspection PyArgumentList
            return ImportFromAST(
                tok_from=tok_from,
                tok_import=tok_import,
                qualified_name=qualified_name,
                aliases=aliases,
                tok_newline=tok_newline
            )
        elif self.match(TokenID.Import):
            tok_import = self.consume(TokenID.Import)
            aliases = self.parse_aliases()
            tok_newline = self.resume(TokenID.NewLine)

            return ImportAST(tok_import=tok_import, aliases=aliases, tok_newline=tok_newline)

        self.match(*self.IMPORTS_STARTS)

    def parse_qualified_name(self) -> QualifiedNameAST:
        """
        qualified_name:
            Name { '.' Name }
        """
        names = [self.consume(TokenID.Name)]
        while self.match(TokenID.Dot):
            names.append(self.consume(TokenID.Dot))
            names.append(self.consume(TokenID.Name))
        return QualifiedNameAST(names=SyntaxCollection(names))

    def parse_aliases(self) -> Sequence[AliasAST]:
        """
        aliases:
            alias { ',' alias }
        """
        aliases = [self.parse_alias()]
        while self.match(TokenID.Comma):
            aliases.append(self.consume(TokenID.Comma))
            aliases.append(self.parse_alias())

        return SyntaxCollection(aliases)

    def parse_alias(self):
        """
        alias:
            qualified_name [ 'as' Name ]
        """
        qualified_name = self.parse_qualified_name()
        if self.match(TokenID.As):
            tok_as = self.consume(TokenID.As)
            tok_alias = self.consume(TokenID.Name)
        else:
            tok_as = None
            tok_alias = None

        return AliasAST(qualified_name=qualified_name, tok_as=tok_as, tok_alias=tok_alias)

    def parse_attributes(self) -> Sequence[AttributeAST]:
        """
        attributes:
            [ '[' '[' attribute { ',' attribute } ']' ']' new_line ] '\n'
        """
        if not self.match(TokenID.LeftSquare):
            return SyntaxCollection(location=self.previous_location)

        attributes = [
            self.consume(TokenID.LeftSquare),
            self.consume(TokenID.LeftSquare),
            self.parse_attribute()
        ]
        while self.match(TokenID.Name):
            attributes.append(self.parse_attribute())

        attributes.extend([
            self.consume(TokenID.RightSquare),
            self.consume(TokenID.RightSquare),
            self.consume(TokenID.NewLine),
        ])
        return SyntaxCollection(attributes)

    def parse_attribute(self) -> AttributeAST:
        """
        attribute:
            Name [ '(' arguments ')' ]
        """
        tok_name = self.consume(TokenID.Name)
        if self.match(TokenID.LeftParenthesis):
            tok_open = self.consume(TokenID.LeftParenthesis)
            arguments = self.parse_arguments()
            tok_close = self.consume(TokenID.RightParenthesis)
        else:
            tok_open = None
            arguments = SyntaxCollection(location=self.previous_location)
            tok_close = None

        # noinspection PyArgumentList
        return AttributeAST(tok_name=tok_name, tok_open=tok_open, arguments=arguments, tok_close=tok_close)

    def parse_members(self) -> Sequence[MemberAST]:
        """
        members:
            { member }
        """
        members = []
        while self.match(*self.MEMBERS_STARTS):
            members.append(self.parse_member())
        return SyntaxCollection(members, location=self.previous_location)

    def parse_member(self) -> MemberAST:
        """
        member:
            function
            class
            struct
            pass_member
            named_member
        """
        if self.match(TokenID.LeftSquare):
            attributes = self.parse_attributes()

            # Check required tokens
            self.match(TokenID.Def, TokenID.Class, TokenID.String, TokenID.Name)
        else:
            attributes = SyntaxCollection(location=self.previous_location)

        if self.match(TokenID.Def):
            return self.parse_function(attributes)
        elif self.match(TokenID.Class):
            return self.parse_class(attributes)
        elif self.match(TokenID.Struct):
            return self.parse_struct(attributes)
        elif self.match(TokenID.Pass):
            return self.parse_pass_member()
        elif self.match(TokenID.Name):
            return self.parse_named_member(attributes)

        self.match(*self.MEMBERS_STARTS)

    def parse_class(self, attributes: Sequence[AttributeAST]) -> ClassAST:
        """
        class:
            'class' Name generic_parameters ':' type_members
        """
        tok_class = self.consume(TokenID.Class)
        tok_name = self.consume(TokenID.Name)
        generic_parameters = self.parse_generic_parameters()
        members = self.parse_type_members()

        # noinspection PyArgumentList
        return ClassAST(
            attributes=attributes,
            tok_class=tok_class,
            tok_name=tok_name,
            generic_parameters=generic_parameters,
            members=members
        )

    def parse_struct(self, attributes: Sequence[AttributeAST]) -> StructAST:
        """
        struct:
            'struct' Name generic_parameters ':' type_members
        """
        tok_struct = self.consume(TokenID.Struct)
        tok_name = self.consume(TokenID.Name)
        members = self.parse_type_members()
        generic_parameters = self.parse_generic_parameters()

        # noinspection PyArgumentList
        return StructAST(
            attributes=attributes,
            tok_struct=tok_struct,
            tok_name=tok_name,
            generic_parameters=generic_parameters,
            members=members,
        )

    def parse_type_members(self) -> Sequence[MemberAST]:
        """
        type_members:
            ':' '...' '\n'
            ':' '\n' Indent members Undent
        """
        self.consume(TokenID.Colon)

        if self.match(TokenID.Ellipsis):
            tok_ellipsis = self.consume(TokenID.Ellipsis)
            tok_newline = self.consume(TokenID.NewLine)
            return SyntaxCollection([tok_ellipsis, tok_newline])

        members = []
        members.append(self.consume(TokenID.NewLine))
        members.append(self.consume(TokenID.Indent))
        members.extend(self.parse_members().children)
        members.append(self.consume(TokenID.Undent))
        return SyntaxCollection(members)

    def parse_pass_member(self) -> PassMemberAST:
        """ pass_member: pass """
        tok_pass = self.consume(TokenID.Pass)
        tok_newline = self.consume(TokenID.NewLine)

        # noinspection PyArgumentList
        return PassMemberAST(tok_pass=tok_pass, tok_newline=tok_newline)

    def parse_named_member(self, attributes: Sequence[AttributeAST]) -> FieldAST:
        """
        named_member:
            Name ':' type
        """
        tok_name = self.consume(TokenID.Name)
        tok_colon = self.consume(TokenID.Colon)
        field_type = self.parse_type()
        tok_newline = self.consume(TokenID.NewLine)

        # noinspection PyArgumentList
        return FieldAST(
            attributes=attributes,
            tok_name=tok_name,
            tok_colon=tok_colon,
            type=field_type,
            tok_newline=tok_newline
        )

    def parse_function(self, attributes: Sequence[AttributeAST]) -> FunctionAST:
        """
        function:
            attributes 'def' Name generic_parameters '(' parameters ')' [ '->' type ] ':' NewLine function_statement
        """
        tok_def = self.consume(TokenID.Def)
        tok_name = self.consume(TokenID.Name)
        generic_parameters = self.parse_generic_parameters()
        tok_open = self.consume(TokenID.LeftParenthesis)
        parameters = self.parse_parameters()
        tok_close = self.consume(TokenID.RightParenthesis)
        if self.match(TokenID.Then):
            tok_then = self.consume(TokenID.Then)
            return_type = self.parse_type()
        else:
            # noinspection PyArgumentList
            tok_then = None
            return_type = AutoTypeAST(location=tok_name.location)
        tok_colon = self.consume(TokenID.Colon)
        statement = self.parse_function_statement()

        # noinspection PyArgumentList
        return FunctionAST(
            attributes=attributes,
            tok_def=tok_def,
            tok_name=tok_name,
            generic_parameters=generic_parameters,
            tok_open=tok_open,
            parameters=parameters,
            tok_close=tok_close,
            tok_then=tok_then,
            return_type=return_type,
            tok_colon=tok_colon,
            statement=statement
        )

    def parse_parameters(self) -> Sequence[ParameterAST]:
        """
        parameters:
            [ parameter { ',' parameter } ]
        """
        parameters = []
        if self.match(TokenID.Name):
            parameters.append(self.parse_parameter())
            while self.match(TokenID.Comma):
                parameters.append(self.consume(TokenID.Comma))
                parameters.append(self.parse_parameter())

        return SyntaxCollection(parameters, location=self.previous_location)

    def parse_parameter(self) -> ParameterAST:
        """
        parameter:
            Name [ ':' type ]
        """
        tok_name = self.consume(TokenID.Name)
        if self.match(TokenID.Colon):
            tok_colon = self.consume(TokenID.Colon)
            param_type = self.parse_type()
        else:
            tok_colon = None
            # noinspection PyArgumentList
            param_type = AutoTypeAST(location=tok_name.location)

        # noinspection PyArgumentList
        return ParameterAST(tok_name=tok_name, tok_colon=tok_colon, type=param_type)

    def parse_function_statement(self) -> Optional[StatementAST]:
        """
        function_statement:
            '...' EndFile
            NewLine block_statement
        """
        if self.match(TokenID.Ellipsis):
            tok_ellipsis = self.consume(TokenID.Ellipsis)
            tok_newline = self.consume(TokenID.NewLine)
            return EllipsisStatementAST(tok_ellipsis=tok_ellipsis, tok_newline=tok_newline)

        self.consume(TokenID.NewLine)
        return self.parse_block_statement()

    def parse_block_statement(self) -> StatementAST:
        """
        block_statement:
            Indent statement { statement } Undent
        """
        statements = [
            self.consume(TokenID.Indent),
            self.parse_statement()
        ]
        while self.match(*self.STATEMENT_STARTS):
            statements.append(self.parse_statement())
        statements.append(self.consume(TokenID.Undent))

        # noinspection PyArgumentList
        return BlockStatementAST(statements=SyntaxCollection(statements))

    def parse_statement(self) -> StatementAST:
        """
        statement:
            pass_statement
            return_statement
            expression_statement
            condition_statement
            while_statement
        """
        if self.match(TokenID.Pass):
            return self.parse_pass_statement()
        elif self.match(TokenID.Return):
            return self.parse_return_statement()
        elif self.match(TokenID.If):
            return self.parse_condition_statement()
        elif self.match(TokenID.While):
            return self.parse_while_statement()
        elif self.match(*self.EXPRESSION_STARTS):
            return self.parse_expression_statement()

        self.consume(*self.STATEMENT_STARTS)

    def parse_pass_statement(self) -> StatementAST:
        """ pass_statement: pass """
        tok_pass = self.consume(TokenID.Pass)
        tok_newline = self.consume(TokenID.NewLine)

        # noinspection PyArgumentList
        return PassStatementAST(tok_pass=tok_pass, tok_newline=tok_newline)

    def parse_return_statement(self) -> StatementAST:
        """
        return_statement
            'return' [ expression ]
        """
        tok_return = self.consume(TokenID.Return)
        value = self.parse_expression() if self.match(*self.EXPRESSION_STARTS) else None
        self.consume(TokenID.NewLine)

        # noinspection PyArgumentList
        return ReturnStatementAST(tok_return, value=value)

    def parse_else_statement(self):
        """
        else_statement:
            'else' ':' '\n' block_statement
        """
        tok_else = self.consume(TokenID.Else)
        tok_colon = self.consume(TokenID.Colon)
        tok_newline = self.consume(TokenID.NewLine)
        statement = self.parse_block_statement()
        return ElseStatementAST(
            tok_else=tok_else,
            tok_colon=tok_colon,
            tok_newline=tok_newline,
            statement=statement
        )

    def parse_condition_statement(self, token_id: TokenID = TokenID.If) -> StatementAST:
        """
        condition_statement:
            'if' expression ':' '\n' block_statement            ⏎
                { 'elif' expression ':' '\n' block_statement }  ⏎
                [ else_statement ]
        """
        tok_if = self.consume(token_id)
        condition = self.parse_expression()
        tok_colon = self.consume(TokenID.Colon)
        tok_newline = self.consume(TokenID.NewLine)
        then_statement = self.parse_block_statement()

        else_statement = None
        if self.match(TokenID.Else):
            else_statement = self.parse_else_statement()
        elif self.match(TokenID.Elif):
            else_statement = self.parse_condition_statement(TokenID.Elif)

        # noinspection PyArgumentList
        return ConditionStatementAST(
            tok_if=tok_if,
            condition=condition,
            tok_colon=tok_colon,
            tok_newline=tok_newline,
            then_statement=then_statement,
            else_statement=else_statement,
        )

    def parse_while_statement(self) -> StatementAST:
        """
        while_statement:
            'while' expression ':' '\n' block_statement     ⏎
                [ 'else' ':' '\n' block_statement ]
        """
        tok_while = self.consume(TokenID.While)
        condition = self.parse_expression()
        tok_colon = self.consume(TokenID.Colon)
        tok_newline = self.consume(TokenID.NewLine)
        then_statement = self.parse_block_statement()
        else_statement = self.parse_else_statement() if self.match(TokenID.Else) else None

        # noinspection PyArgumentList
        return WhileStatementAST(
            tok_while=tok_while,
            condition=condition,
            tok_colon=tok_colon,
            tok_newline=tok_newline,
            then_statement=then_statement,
            else_statement=else_statement,
        )

    def parse_expression_statement(self) -> StatementAST:
        """
        expression_statement
            expression
            assign_expression
        """
        expression = self.parse_expression()
        statement = None

        if self.match(TokenID.Equals):
            statement = self.parse_assign_statement(expression)

        tok_newline = self.consume(TokenID.NewLine)
        if not statement:
            # noinspection PyArgumentList
            statement = ExpressionStatementAST(value=expression, tok_newline=tok_newline)
        return statement

    def parse_assign_statement(self, target: ExpressionAST):
        """
        assign_expression
            target '=' expression
        """
        tok_equals = self.consume(TokenID.Equals)
        source = self.parse_expression()

        # noinspection PyArgumentList
        return AssignStatementAST(
            target=target,
            tok_equals=tok_equals,
            source=source,
        )

    def parse_arguments(self) -> Sequence[ExpressionAST]:
        """
        arguments:
            [ expression { ',' expression } [','] ]
        """
        if not self.match(*self.EXPRESSION_STARTS):
            return tuple()

        arguments = [self.parse_expression()]
        while self.match(TokenID.Comma):
            self.consume(TokenID.Comma)
            if self.match(*self.EXPRESSION_STARTS):
                arguments.append(self.parse_expression())
            else:
                break

        return tuple(arguments)

    def parse_expression(self) -> ExpressionAST:
        """
        expression:
            atom
        """
        return self.parse_addition_expression()

    def parse_addition_expression(self) -> ExpressionAST:
        """
        addition_expression:
            multiplication_expression
            addition_expression '+' multiplication_expression
            addition_expression '-' multiplication_expression
        """
        expression = self.parse_multiplication_expression()
        while self.match(TokenID.Plus, TokenID.Minus):
            if self.match(TokenID.Plus):
                tok_operator = self.consume(TokenID.Plus)
                right_operand = self.parse_unary_expression()

                # noinspection PyArgumentList
                expression = BinaryExpressionAST(
                    operator=BinaryID.Add,
                    left_operand=expression,
                    right_operand=right_operand,
                    tok_operator=tok_operator
                )
            elif self.match(TokenID.Minus):
                tok_operator = self.consume(TokenID.Minus)
                right_operand = self.parse_unary_expression()

                # noinspection PyArgumentList
                expression = BinaryExpressionAST(
                    operator=BinaryID.Sub,
                    left_operand=expression,
                    right_operand=right_operand,
                    tok_operator=tok_operator,
                )
        return expression

    def parse_multiplication_expression(self) -> ExpressionAST:
        """
        multiplication_expression:
            unary_expression
            multiplication_expression '*' unary_expression
            # multiplication_expression '@' multiplication_expression
            multiplication_expression '//' unary_expression
            multiplication_expression '/' unary_expression
            # multiplication_expression '%' unary_expression
        """
        expression = self.parse_unary_expression()
        while self.match(TokenID.Star, TokenID.Slash, TokenID.DoubleSlash):
            if self.match(TokenID.Star):
                tok_operator = self.consume(TokenID.Star)
                right_operand = self.parse_unary_expression()

                # noinspection PyArgumentList
                expression = BinaryExpressionAST(
                    operator=BinaryID.Mul,
                    left_operand=expression,
                    right_operand=right_operand,
                    tok_operator=tok_operator,
                )

            elif self.match(TokenID.Slash):
                tok_operator = self.consume(TokenID.Slash)
                right_operand = self.parse_unary_expression()

                # noinspection PyArgumentList
                expression = BinaryExpressionAST(
                    operator=BinaryID.Div,
                    left_operand=expression,
                    right_operand=right_operand,
                    tok_operator=tok_operator,
                )

            elif self.match(TokenID.DoubleSlash):
                tok_operator = self.consume(TokenID.DoubleSlash)
                right_operand = self.parse_unary_expression()

                # noinspection PyArgumentList
                expression = BinaryExpressionAST(
                    operator=BinaryID.DoubleDiv,
                    left_operand=expression,
                    right_operand=right_operand,
                    tok_operator=tok_operator,
                )

        return expression

    def parse_unary_expression(self) -> ExpressionAST:
        """
        u_expr:
            power
            "-" u_expr
            "+" u_expr
            "~" u_expr
        """
        if self.match(TokenID.Minus):
            tok_operator = self.consume(TokenID.Minus)
            operand = self.parse_unary_expression()

            # noinspection PyArgumentList
            return UnaryExpressionAST(operator=UnaryID.Neg, operand=operand, tok_operator=tok_operator)

        elif self.match(TokenID.Plus):
            tok_operator = self.consume(TokenID.Plus)
            operand = self.parse_unary_expression()

            # noinspection PyArgumentList
            return UnaryExpressionAST(operator=UnaryID.Pos, operand=operand, tok_operator=tok_operator)

        elif self.match(TokenID.Tilde):
            tok_operator = self.consume(TokenID.Tilde)
            operand = self.parse_unary_expression()

            # noinspection PyArgumentList
            return UnaryExpressionAST(operator=UnaryID.Inv, operand=operand, tok_operator=tok_operator)

        return self.parse_power_expression()

    def parse_power_expression(self) -> ExpressionAST:
        """
        power:
            primary ["**" u_expr]
        """
        expression = self.parse_primary_expression()
        if self.match(TokenID.DoubleStar):
            tok_operator = self.consume(TokenID.DoubleStar)
            unary_expression = self.parse_unary_expression()

            # noinspection PyArgumentList
            expression = BinaryExpressionAST(
                operator=BinaryID.Pow,
                left_operand=expression,
                right_operand=unary_expression,
                tok_operator=tok_operator
            )
        return expression

    def parse_primary_expression(self) -> ExpressionAST:
        """
        primary:
             number_expression
             name_expression
             call_expression
             parenthesis_expression
             subscribe_expression
             attribute_expression
        """
        if self.match(TokenID.Number):
            expression = self.parse_number_expression()
        elif self.match(TokenID.Name):
            expression = self.parse_name_expression()
        elif self.match(TokenID.LeftParenthesis):
            expression = self.parse_parenthesis_expression()
        else:
            raise self.match(*self.EXPRESSION_STARTS)  # Make linter happy

        while self.match(TokenID.LeftParenthesis, TokenID.LeftSquare, TokenID.Dot):
            if self.match(TokenID.LeftParenthesis):
                expression = self.parse_call_expression(expression)
            elif self.match(TokenID.LeftSquare):
                expression = self.parse_subscribe_expression(expression)
            elif self.match(TokenID.Dot):
                expression = self.parse_attribute_expression(expression)
        return expression

    def parse_number_expression(self) -> ExpressionAST:
        """
        number:
            Number
        """
        tok_number = self.consume(TokenID.Number)

        # noinspection PyArgumentList
        return IntegerExpressionAST(tok_number=tok_number)

    def parse_name_expression(self) -> ExpressionAST:
        """
        name:
            Name
        """
        tok_name = self.consume(TokenID.Name)

        # noinspection PyArgumentList
        return NamedExpressionAST(tok_name=tok_name)

    def parse_call_expression(self, value: ExpressionAST) -> ExpressionAST:
        """
        call_expression
            atom '(' arguments ')'
        """
        tok_open = self.consume(TokenID.LeftParenthesis)
        arguments = self.parse_arguments()
        tok_close = self.consume(TokenID.RightParenthesis)

        # noinspection PyArgumentList
        return CallExpressionAST(value=value, tok_open=tok_open, arguments=arguments, tok_close=tok_close)

    def parse_subscribe_expression(self, value: ExpressionAST) -> ExpressionAST:
        """
        subscribe_expression
            atom '[' arguments ']'
        """
        tok_open = self.consume(TokenID.LeftSquare)
        arguments = self.parse_arguments()
        tok_close = self.consume(TokenID.RightSquare)

        # noinspection PyArgumentList
        return SubscribeExpressionAST(value=value, tok_open=tok_open, arguments=arguments, tok_close=tok_close)

    def parse_attribute_expression(self, value: ExpressionAST) -> ExpressionAST:
        """
        attribute_expression:
            atom '.' Name
        """
        tok_dot = self.consume(TokenID.Dot)
        tok_name = self.consume(TokenID.Name)

        # noinspection PyArgumentList
        return AttributeExpressionAST(value=value, tok_dot=tok_dot, tok_name=tok_name)

    def parse_parenthesis_expression(self) -> ExpressionAST:
        """
        parenthesis_expression:
            '(' expression ')'
        """
        self.consume(TokenID.LeftParenthesis)
        expression = self.parse_expression()
        self.consume(TokenID.RightParenthesis)
        return expression
